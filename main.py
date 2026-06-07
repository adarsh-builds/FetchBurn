from bs4 import BeautifulSoup
import requests

print("FetchBurn starting...")
#fetching data from API

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
    for link in links:
        href = link.get('href')
        if href and href.endswith('.iso') and href not in seen:
            print(href)
            seen.add(href)  # Add the href to the seen set

else:
    print(f"Error message: {response.text}")