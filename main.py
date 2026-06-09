import os
import sys
import json
from bs4 import BeautifulSoup
import requests
from tqdm import tqdm
import hashlib
import subprocess
import ctypes

print("FetchBurn starting...")
#fetching data from API

response = requests.get("https://api.launchpad.net/1.0/ubuntu/series")

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False
if not is_admin():
    print("This script must be run with administrator privileges. Please run it as an administrator.")
    print("Requesting administrator privileges...")
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)

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
                t=tqdm(total=total_size, unit='B', unit_scale=True, leave=False, desc=filename)
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=10*1024*1024):  # 10 MB chunks
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

    print("Available drives:")
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
    
    print("Attempting to write the ISO file to a removable drive...")
    usb_drives = find_usb_physical_drives()
    
else:
    print(f"Error message: {response.text}")