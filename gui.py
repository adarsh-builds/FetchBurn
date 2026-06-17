import customtkinter as ctk
import fetchburn_core
import ctypes
import sys
import os
import threading

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class FetchBurnGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("FetchBurn")
        self.geometry("500x400")

        self.my_title = ctk.CTkLabel(self, text="FetchBurn Universal Flasher", font=ctk.CTkFont(size=24, weight="bold"))
        self.my_title.pack(pady=20)

        self.status_label = ctk.CTkLabel(self, text="Status: Idle", font=ctk.CTkFont(size=16))
        self.status_label.pack(pady=10)

        self.my_button = ctk.CTkButton(self, text="Fetch Ubuntu Details", command=self.test_backend)
        self.my_button.pack()

    def start_thread(self):
        """This runs instantly on the main GUI thread when clicked."""
        self.status_label.configure(text="Fetching data...")
        self.my_button.configure(state="disabled")

        worker = threading.Thread(target=self.run_backend)
        worker.start()
    
    def test_backend(self):
        """This runs completely in the background"""
        url, version, base, filename = fetchburn_core.fetch_ubuntu_iso_details()
    
        if version:
            self.status_label.configure(text=f"Success! Found: {filename}")
        else:
            self.status_label.configure(text="Failed to fetch data.")
        self.my_button.configure(state="normal")

if __name__ == "__main__":
    if not fetchburn_core.is_admin():
        python_runner = sys.executable.replace("python.exe", "pythonw.exe")
        
        script=os.path.abspath(sys.argv[0])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", python_runner, f'"{script}"', None, 1)

        os._exit(0)

    app = FetchBurnGUI()
    app.mainloop()