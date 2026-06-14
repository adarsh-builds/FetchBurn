import os
import sys
import json
from bs4 import BeautifulSoup
import requests
from tqdm import tqdm
import hashlib
import subprocess
import ctypes
import win32file
import win32con
import winioctlcon


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False
    
def get_drive_letter(device_id):
    ps_command = f"""
    $disk = Get-Disk -Number {device_id}
    $partitions = Get-Partition -DiskNumber {device_id} | Where-Object {{ $_.DriveLetter }}
    $partitions[0].DriveLetter
    """
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], capture_output=True, text=True, check=True)
    return result.stdout.strip()

def write_iso_with_python(iso_path, device_path, target_drive):
    if not os.path.exists(iso_path):
        print(f"Error: ISO file not found at {iso_path}")
        return False
        
    volume_handle = None  # Initialize as None at the very beginning
    
    try:
        # Unmount the drive if it's mounted
        drive_letter = get_drive_letter(target_drive['DeviceID'])
        print(f"Detected drive letter: {target_drive['FriendlyName']}: {drive_letter}")
        
        if drive_letter:
            volume_path = f"\\\\.\\{drive_letter}:"
            print(f"Attempting to unmount drive {drive_letter}...")         
            try:
                volume_handle = win32file.CreateFile(
                    volume_path,
                    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                    None,
                    win32con.OPEN_EXISTING,
                    0,
                    None
                )
                win32file.DeviceIoControl(volume_handle, winioctlcon.FSCTL_LOCK_VOLUME, None, 0)
                win32file.DeviceIoControl(volume_handle, winioctlcon.FSCTL_DISMOUNT_VOLUME, None, 0)
                print(f"Drive {target_drive['FriendlyName']} unmounted successfully.")
            except Exception as e:
                print(f"Could not unmount the drive: {e}")

        print(f"Writing {iso_path} to {device_path}...")
        
        total_size = os.path.getsize(iso_path)
        chunk_size = 16 * 1024 * 1024  # 16MB chunks for maximum speed
        sector_size = 512             # Standard physical sector size
        
        # r+b is critical! 'wb' tells Windows to truncate the file, which crashes on raw physical drives
        with open(iso_path, 'rb') as f_in, open(device_path, 'r+b', buffering=0) as f_out:
            with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024, desc="Flashing ISO") as pbar:
                while True:
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break 
                    
                    # --- PADDING ---
                    # Windows raw disk writes must perfectly align with the 512-byte sector size.
                    remainder = len(chunk) % sector_size
                    if remainder != 0:
                        padding_needed = sector_size - remainder
                        chunk += b'\x00' * padding_needed
                    # ---------------

                    f_out.write(chunk)
                    pbar.update(min(len(chunk), total_size - pbar.n))
        
        print("\nISO file written to the drive successfully!")
        return True

    except PermissionError:
        print("\nAccess Denied: You must run this script as an Administrator to write to raw drives.")
        return False
    except OSError as e:
        print(f"\nOS Error occurred: {e}")
        print("Did you make sure to dismount and lock the drive first?")
        return False
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        return False
        
    finally:
        # This block will ALWAYS run at the end, safely releasing the drive
        if volume_handle:
            try:
                win32file.CloseHandle(volume_handle)
                print("Drive lock released gracefully.")
            except Exception as e:
                print(f"Failed to release drive lock: {e}")

def find_usb_physical_drives():
    if sys.platform != "win32":
        print("This drive detection method is only implemented for Windows.")
        return []
    print("Detecting removable drives on Windows...")
    ps_command = "get-physicaldisk | where-object { $_.BusType -eq 'USB' } | select-object DeviceID, FriendlyName | ConvertTo-Json"
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output:
            print("No removable drives detected.")
            return []
        disks = json.loads(output)

        if isinstance(disks, dict):
            disks = [disks]  # Handle single drive case

        for disk in disks:
            print(f"DeviceID: {disk['DeviceID']}, FriendlyName: {disk['FriendlyName']}")
        return disks
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while detecting drives: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Failed to parse drive information: {e}")
        return []

def create_data_partition(drive_number):
    ps_command = f"""
    # 1. Force Windows to rescan the hardware after the raw flash
    Update-HostStorageCache
    Start-Sleep -Seconds 2
    
    $disk = Get-Disk -Number {drive_number}
    
    # 2. Safely read partitions, ignoring errors if Windows panics over the Linux format
    $partitions = Get-Partition -DiskNumber {drive_number} -ErrorAction SilentlyContinue
    $usedSpace = 0
    if ($partitions) {{
        $usedSpace = ($partitions | Measure-Object -Property Size -Sum).Sum
    }}
    
    $unallocated = $disk.Size - $usedSpace
    
    # 3. Only attempt creation if there is actually more than 1GB of free space left
    if ($unallocated -gt 1GB) {{
        # 4. Use exFAT to bypass the 32GB FAT32 crash limit
        New-Partition -DiskNumber {drive_number} -UseMaximumSize | Format-Volume -FileSystem exFAT -NewFileSystemLabel "FetchBurnData" -Confirm:$false
        Write-Output "Successfully created FetchBurnData partition."
    }} else {{
        Write-Output "Skipped: Not enough unallocated space to create a usable data partition."
    }}

    # 5. Assign a drive letter to the new partition if it exists
    Get-Partition -DiskNumber {drive_number} | Where-Object {{ !$_.DriveLetter }} | Add-PartitionAccessPath -AssignDriveLetter
    """
    
    try:
        print("\nRefreshing disk state and calculating unallocated space...")
        # Added capture_output and text=True so Python can read the PowerShell logs
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command], 
            check=True, 
            capture_output=True, 
            text=True
        )
        if result.stdout:
            print(result.stdout.strip())
            
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Failed to create the data partition.")
        # THIS will finally print the exact PowerShell error in red text
        print(f"Windows Error Details:\n{e.stderr.strip()}")

def restore_drive(drive_number):
    ps_command = f"""
    $disk = Get-Disk -Number {drive_number}
    $partitions = Get-Partition -DiskNumber {drive_number}
    foreach ($partition in $partitions) {{
        Remove-Partition -DiskNumber {drive_number} -PartitionNumber $partition.PartitionNumber -Confirm:$false
    }}
    Clear-Disk -Number {drive_number} -RemoveData -Confirm:$false
    Initialize-Disk -Number {drive_number} -PartitionStyle MBR
    New-Partition -DiskNumber {drive_number} -UseMaximumSize | Format-Volume -FileSystem FAT32 -NewFileSystemLabel "Restored Drive" -Confirm:$false
    Get-Partition -DiskNumber {drive_number} | Where-Object {{ !$_.DriveLetter }} | Add-PartitionAccessPath -AssignDriveLetter
    """
    try:
        print(f"Restoring drive {drive_number} to FAT32. This will erase all data...")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            check=True,
            capture_output=True,
            text=True
        )
        print("Drive restored successfully.")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Restore failed: {e.stderr}")
        return False
    return True

if not is_admin():
    print("This script must be run with administrator privileges. Please run it as an administrator.")
    print("Requesting administrator privileges...")
    script = os.path.abspath(sys.argv[0])
    ctypes.windll.shell32.ShellExecuteW(None,
                                        "runas",
                                        sys.executable,
                                        f'"{script}"',
                                        None,
                                        1)
    sys.exit()

print("FetchBurn starting...")
#fetching data from API
while True:
    action = input(f"Do you want to write or restore: (write/restore/exit): ")

    if action.lower() == 'exit':
        print("Exiting the program.")
        break

    elif action.lower() == 'write':
        print("You have chosen to write an ISO to a removable drive.")
        response = requests.get("https://api.launchpad.net/1.0/ubuntu/series")

        if response.status_code == 200:
            print("Data fetched successfully!")
            data = response.json()
            entries = data['entries']
                
            print(f"Total releases found: {len(entries)}")
            
            stable = None 
            for release in entries:
                if release.get('status') == 'Current Stable Release':
                    stable = release
                    break # Stop at first match — only one stable release exists

            version = stable.get('version')
            print(f"Latest stable release: {version}")

            url = f"https://releases.ubuntu.com/{version}/"
            response = requests.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')  
            links = soup.find_all('a')
            
            seen = set()  # Deduplicate ISO links - releases page lists each file twice
            download_url = None
            for link in links:
                href = link.get('href')
                if href and 'desktop' in href and href.endswith('.iso') and href not in seen:
                    download_url = url + href
                    seen.add(href)
                    break
            if not download_url:
                print("No desktop ISO found.")
                exit()
            
            filename = f"ubuntu-{version}-desktop-amd64.iso"
            save_path = os.path.join(os.getcwd(), filename)
            if os.path.exists(save_path):
                print(f"{filename} already exists at {save_path}. Skipping download.")
            else:
                print(f"Now downloading {filename} at {save_path}...")
                try:
                    with requests.get(download_url, stream=True) as r:
                        total_size = int(r.headers.get('content-length', 0))
                        print(f"File size: {total_size / (1024 * 1024):.2f} MB")
                        r.raise_for_status()
                        with open(save_path, 'wb') as f:
                            with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename) as t:
                                for chunk in r.iter_content(chunk_size=10*1024*1024):
                                    f.write(chunk)
                                    t.update(len(chunk))
                    print("Download completed successfully!")
                except Exception as e:
                    print(f"An error occurred during download: {e}")
            
            # Verify the file integrity using SHA256 checksum

            print("Verifying file integrity...")
            sha256_hash = hashlib.sha256()
            try:
                with open(save_path, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                computed_checksum = sha256_hash.hexdigest()
                print(f"Computed SHA256 checksum: {computed_checksum}")
            except Exception as e:
                print(f"An error occurred during checksum calculation: {e}")
            
            for link in links:
                href = link.get('href')
                if href and href.endswith('SHA256SUMS'):
                    checksum_url = url + href
                    print(f"Fetching official checksums from {checksum_url}...")
                    try:
                        checksum_response = requests.get(checksum_url)
                        checksum_response.raise_for_status()
                        checksums = checksum_response.text
                        for line in checksums.splitlines():
                            if filename in line:
                                official_checksum = line.split()[0]
                                print(f"Official SHA256 checksum: {official_checksum}")
                                if computed_checksum == official_checksum:
                                    print("Checksum verification passed! The file is valid.")
                                else:
                                    print("Checksum verification failed! The file may be corrupted.")
                                break
                    except Exception as e:
                        print(f"An error occurred while fetching or processing checksums: {e}")

            # Write the download ISO file to a removable drive      
            # Write the download ISO file to a removable drive      
            print("\nAttempting to write the ISO file to a removable drive...")
            usb_drives = find_usb_physical_drives()
            
            if usb_drives:
                # Note: You can replace this with an interactive menu later!
                target_drive = usb_drives[0] 
                device_path = f"\\\\.\\PhysicalDrive{target_drive['DeviceID']}"
                
                print(f"Target selected: {target_drive['FriendlyName']}")
                confirm = input(f"Are you sure you want to write {filename} to {target_drive['FriendlyName']}? This will ERASE ALL DATA. (yes/no): ")
                
                if confirm.lower() == 'yes':
                    print(f"Starting flash process for {target_drive['FriendlyName']}...")
                    
                    # --- The Magic Happens Here ---
                    # All locking, unmounting, flashing, and unlocking is handled inside this single call.
                    if write_iso_with_python(save_path, device_path, target_drive):
                        print("Base operation completed successfully!")
                        create_data_partition(target_drive['DeviceID'])
                    else:
                        print("Operation failed during the flash process.")
                    # ------------------------------
                    
                else:
                    print("Operation cancelled by user.")
            else:
                print("No removable drives detected.")
                
        else:
            print(f"Error message: {response.text}")
            
    elif action.lower() == 'restore':
        print("You have chosen to restore a drive")
        usb_drives = find_usb_physical_drives()
        if usb_drives:
            target_drive = usb_drives[0]
            confirm_wipe = input (f"Are you sure you want to wipe the drive {target_drive['FriendlyName']}? This will erase all data on the drive. (yes/no): ")
            if confirm_wipe.lower() == 'yes':
                restore_drive(target_drive['DeviceID'])
            else:
                print("Operation cancelled.")
        else:
            print("No removable drives detected.")

    else:
        print("Invalid action. Please choose 'write', 'restore', or 'exit'.")
        continue

    print("\n" + "-"*40)
    go_again = input("Do you want to perform another operation? (yes/no): ").strip().lower()
    if go_again != 'yes':
        print("Thank you for using FetchBurn. Goodbye!")
        break

input("\nPress Enter to exit...")