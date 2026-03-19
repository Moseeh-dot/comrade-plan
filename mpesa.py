import requests
from requests.auth import HTTPBasicAuth

# --- COMTRADE PLAN: DARAJA CREDENTIALS ---
# Keep these safe! Never commit the real production keys to GitHub later.
CONSUMER_KEY = "wr3aTUAOQWFCLrbEkuyvYDZydoQCxbGxzqrEMOQIn6fxr04f"
CONSUMER_SECRET = "2sYAzSRdl0wmZc6T3swMuY1xnE7Z6unNZEDsYEa0tKq0TKa9SdBW2iPyJPKucl6Y"

def get_access_token():
    """
    Traders our Consumer Key and Secret for a 60-minute Access Token from Safaricom.
    """
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    try:
        # We use HTTP Basic Auth to securely transmit the keys
        response = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        
        # Safaricom returns a JSON envelope. We extract just the token string.
        json_response = response.json()
        access_token = json_response['access_token']
        
        print("✅ Handshake Successful!")
        print(f"Your temporary Access Token is: {access_token}")
        
        return access_token
        
    except Exception as e:
        print(f"❌ Handshake Failed: {e}")
        return None

# This allows us to test the file directly in the terminal
if __name__ == "__main__":
    get_access_token()
