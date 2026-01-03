import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v21.5", page_icon="⚡", layout="wide")

# --- 2. API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None

# --- 3. HJELPEFUNKSJONER ---

def hent_tesla_lader(lat, lon):
    # Søker etter Tesla Superchargers innenfor 5km radius fra ruten
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&keyword=Tesla+Supercharger&key={API_KEY}"
    try:
        res = requests.get(url, timeout=3).json()
        if res['status'] == 'OK' and res['results']:
            navn = res['results'][0]['name']
            return f"⚡ {navn}"
    except: pass
    return ""

def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v21.5'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        timeseries = data['properties']['timeseries']
        best_match = min(timeseries, key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        details = best_match['data']['instant']['details']
        return {
            "temp": details.get('air_temperature', 0),
            "vind": details.get('wind_speed', 0),
            "symbol": best_match['data']['next_1_hours']['summary']['symbol_code']
        }
    except: return {"temp": 0, "vind": 0, "symbol": "clearsky_day"}

def hent_hoyde(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        return int(res['results'][0]['elevation']) if res['status'] == 'OK' else 0
    except: return 0

def hent_kommune(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no"
    try:
        res = requests.get(url, timeout=5).json()
        for result in res['results']:
            for component in result['address_components']:
                if "administrative_area_level_2" in component['types']:
                    return component['long_name']
    except: pass
    return "Ukjent"

def analyser_forhold(vaer_data, ankomst_tid, hoyde):
    time = ankomst_tid.hour
    er_morkt = time >= 16 or time <= 9
    sikt_tekst = "Klar sikt"
    sikt_poeng = 0
    
    if "fog" in vaer_data['symbol']: sikt_tekst = "Tåke"; sikt_poeng = 2
    elif "snow" in vaer_data['symbol']: sikt_tekst = "Snøbyger"; sikt_poeng = 2
    if er_morkt: sikt_tekst += " (Mørkt)"; sikt_poeng += 1

    temp = vaer_data['temp']
    score = 1
    if -1.0 <= temp <= 1.0: 
        kjoreforhold = "Svært glatt (nullføre)"; score += 5
    elif temp < -1.0: 
        kjoreforhold = "Vinterføre (is/snø)"; score += 3
    else: 
        kjoreforhold = "Våt veibane" if "rain" in vaer_data['symbol'] else "Tørr veibane"

    if vaer_data['vind'] > 12: score += 2
    score += sikt_poeng

    delay = 10 if score >= 8 else 5 if score >= 5 else 0
    forbruk = "Høyt (Kulde/Stigning)" if (hoyde > 600 or temp < -5) else "Normalt"

    return sikt_tekst, kjoreforhold, min(10, score), delay, forbruk

# --- 4. SIDEBAR ---
st.sidebar.header("📍 Reiseplanlegger m/Lader")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
dato = st.sidebar.date_input("Dato:", value=datetime.now())
tid_v = st.sidebar.time_input("Tid:", value=datetime.now())
start_knapp = st.sidebar.button("🚀 Kjør Analyse", type="primary")

# --- 5. LOGIKK ---
if start_knapp:
    with st.spinner('Leter etter ladere og analyserer vær...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            vei_punkter = polyline.decode(route_res['routes'][0]['overview_polyline']['points'])
            
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="#2196F3", weight=5).add_to(m)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km, total_delay = 0, 0, 0, 0

            for step in leg['steps']:
                dist_km = akk_met / 1000
                if dist_km >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sek + (total_delay * 60))
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    vaer = hent_vaer_detaljer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    kommune = hent_kommune(lat, lon)
                    lader = hent_tesla_lader(lat, lon)
                    sikt, kjore, score, delay, forbruk = analyser_forhold(vaer, ankomst, hoyde)
                    
                    total_delay += delay
                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Ankomst": ankomst.strftime("%H:%M"),
                        "Sted": kommune,
                        "Høyde": hoyde,
                        "Vær": f"{vaer['temp']}°C",
                        "Kjøreforhold": kjore,
                        "Forbruk": forbruk,
                        "Tesla Lader": lader,
                        "Risiko": score
                    })
                    neste_sjekk_km += 50

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.delay = total_delay
            st.session_state.orig_tid = leg['duration']['text']

# --- 6. VISNING ---
if st.session_state.tabell_data:
    df = pd.DataFrame(st.session_state.tabell_data)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Anslått Forsinkelse", f"+{st.session_state.delay} min")
    c2.metric("Total Tid", f"{st.session_state.orig_tid} (+{st.session_state.delay}m)")
    c3.metric("Tesla Ladere", f"{len(df[df['Tesla Lader'] != ''])} funnet", "Langs ruten")

    col1, col2 = st.columns([2, 1])
    with col1:
        components.html(st.session_state.kart_html, height=450)
    with col2:
        st.write("**Høydeprofil (moh)**")
        st.area_chart(df.set_index('KM')['Høyde'], height=350)
        
    st.subheader("📋 Veiplan og Lademuligheter")
    st.dataframe(df, use_container_width=True)
    st.download_button("📥 Last ned reiseplan", df.to_csv().encode('utf-8'), "reiseplan.csv")
