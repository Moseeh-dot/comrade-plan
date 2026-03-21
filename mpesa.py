import requests
import base64
from datetime import datetime
import os
from dotenv import load_dotenv

# Load the local vault if we are running on your laptop
load_dotenv()

# --- COMRADE PLAN: MASTER CREDENTIALS (SECURED) ---
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
PASSKEY = os.getenv("PASSKEY")
BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")

# --- B2C WITHDRAWAL KEYS (SECURED) ---
INITIATOR_NAME = os.getenv("INITIATOR_NAME")
SECURITY_CREDENTIAL = os.getenv("SECURITY_CREDENTIAL")

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
def trigger_b2c_payout(phone_number, amount):
    print("\n--- INITIATING EMERGENCY WITHDRAWAL ---")
    print("Step 1: Getting Access Token...")
    access_token = get_access_token()
    if not access_token:
        return

    print("Step 2: Preparing the Cash Briefcase...")
    api_url = "https://sandbox.safaricom.co.ke/mpesa/b2c/v1/paymentrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "InitiatorName": INITIATOR_NAME,
        "SecurityCredential": SECURITY_CREDENTIAL,
        "CommandID": "BusinessPayment",
        "Amount": amount,
        "PartyA": BUSINESS_SHORTCODE,
        "PartyB": phone_number,
        "Remarks": "Comrade Plan Emergency Withdrawal",
        "QueueTimeOutURL": "https://comrade-plan.onrender.com/api/b2c_timeout",
        "ResultURL": "https://comrade-plan.onrender.com/api/b2c_result",
        "Occasion": "Withdrawal"
    }

    try:
        print(f"Step 3: Commanding Safaricom to send KES {amount} to {phone_number}...")
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        print("\n--- SAFARICOM B2C RESPONSE ---")
        print(response.json())
    except Exception as e:
        print(f"❌ B2C Error: {e}")
if __name__ == "__main__":
    # TESTING ZONE
    my_test_phone = "254758384925" # Make sure your number is here!
    
    # Try to SEND 1 Shilling FROM the Paybill TO your phone
    trigger_b2c_payout(my_test_phone, 1)
    