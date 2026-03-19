import requests
from requests.auth import HTTPBasicAuth
import base64
from datetime import datetime

# --- COMRADE PLAN: MASTER CREDENTIALS ---
CONSUMER_KEY = "wr3aTUAOQWFCLrbEkuyvYDZydoQCxbGxzqrEMOQIn6fxr04f"
CONSUMER_SECRET = "2sYAzSRdl0wmZc6T3swMuY1xnE7Z6unNZEDsYEa0tKq0TKa9SdBW2iPyJPKucl6Y"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
BUSINESS_SHORTCODE = "174379"  # This is the universal Daraja Sandbox Paybill

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET), timeout=10)
        if response.status_code == 200:
            return response.json()['access_token']
        else:
            print(f"❌ Handshake Failed: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def trigger_stk_push(phone_number, amount):
    print("Step 1: Getting Access Token...")
    access_token = get_access_token()
    if not access_token:
        return

    print("Step 2: Securing the Payload (Cryptography)...")
    # Generate exact timestamp (YYYYMMDDHHmmss)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # Mash and scramble the password
    data_to_encode = BUSINESS_SHORTCODE + PASSKEY + timestamp
    encoded_password = base64.b64encode(data_to_encode.encode()).decode('utf-8')

    print("Step 3: Firing STK Push to Safaricom...")
    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "BusinessShortCode": BUSINESS_SHORTCODE,
        "Password": encoded_password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": "https://comrade-plan.onrender.com/api/mpesa_callback", # Where the receipt goes
        "AccountReference": "Comrade Plan",
        "TransactionDesc": "Vault Top Up"
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10 )
        print("\n--- SAFARICOM RESPONSE ---")
        print(response.json())
    except Exception as e:
        print(f"❌ STK Push Error: {e}")

if __name__ == "__main__":
    # TESTING ZONE
    # Enter your actual Safaricom number below. MUST start with 254 (e.g., 254712345678)
    my_test_phone = "254758384925" 
    
    # Let's try to ask your phone for 1 Shilling
    trigger_stk_push(my_test_phone, 1)