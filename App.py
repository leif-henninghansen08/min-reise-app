import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v20", page_icon="🛡️", layout="wide")

# --- 2. API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None

# --- 3. FUNKSJONER ---

def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v20.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        timeseries = data['properties']['timeseries']
        best_match = min(timeseries, key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        
        details = best_match['data']['instant']['details']
        summary = best_match['data']['next_1_hours']['summary']['symbol_code']
        
        return {
            "temp": details.get('air_temperature', 0),
            "vind": details.get('wind_speed', 0),
            "symbol": summary
        }
    except: return {"temp": 0, "vind": 0, "symbol": "clearsky_day"}

def hent_hoyde(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK' and res['results']:
            return int(res['results'][0]['elevation'])
        return 0
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

def analyser_forhold(vaer_data, ankomst_tid):
    sikt_tekst = "Klar sikt"
    sikt_poeng = 0
    time = ankomst_tid.hour
    er_morkt = time >= 17 or time <= 8
    
    symbol = vaer_data['symbol']
    if "fog" in symbol:
        sikt_tekst = "Tåke"; sikt_poeng = 2
    elif "snow" in symbol:
        sikt_tekst = "Snøbyger"; sikt_poeng = 2
    
    if er_morkt:
        sikt_tekst += " + Mørke"
        sikt_poeng += 1

    temp = vaer_data['temp']
    if -1.0 <= temp <= 1.0:
        kjoreforhold = "Svært glatt (nullføre)"
    elif temp < -1.0:
        kjoreforhold = "Vinterføre (is/snø)"
    elif "rain" in symbol:
        kjoreforhold = "Våt veibane"
    else:
        kjoreforhold = "Tørr veibane"

    score = 1
    grunner = []
    if -1.5 <= temp <= 0.5: 
        score += 5; grunner.append("Isfare")
    elif temp < -1.5: 
        score += 3; grunner.append("Vinterføre")
    
    if vaer_data['vind'] > 12: 
        score += 2; grunner.append("Vind")
    
    score += sikt_poeng
    if sikt_poeng >= 2: grunner.append("Dårlig sikt")
    if not grunner: grunner.append("Optimale forhold")
    
    return sikt_tekst, kjoreforhold, min(10, score), ", ".join(grunner)

# --- 4. SIDEBAR ---
st.sidebar.header("📍 Reiseplan")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
dato = st.sidebar.date_input("Dato:", value=datetime.now())
tid_v = st.sidebar.time_input("Tid:", value=datetime.now())
start_knapp = st.sidebar.button("🚀 Kjør Veianalyse", type="primary")

# --- 5. LOGIKK ---
if start_knapp:
    with st.spinner('Henter data...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            vei_punkter = polyline.decode(route_res['routes'][0]['overview_polyline']['points'])
            
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="#2196F3", weight=5).add_to(m)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km = 0, 0, 0

            for step in leg['steps']:
                dist_km = akk_met / 1000
                if dist_km >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sek)
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    vaer = hent_vaer_detaljer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    kommune = hent_kommune(lat, lon)
                    sikt, kjoreforhold, score, arsak = analyser_forhold(vaer, ankomst)
                    
                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Tid": ankomst.strftime("%H:%M"),
                        "Sted": kommune,
                        "Høyde": hoyde,
                        "Vær": f"{vaer['temp']}°C / {sikt}",
                        "Kjøreforhold": kjoreforhold,
                        "Risiko": score,
                        "Merknad": arsak
                    })
                    neste_sjekk_km += 50

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()

# --- 6. VISNING (Responsivt Design) ---
if st.session_state.tabell_data:
    df = pd.DataFrame(st.session_state.tabell_data)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("🗺️ Kart")
        components.html(st.session_state.kart_html, height=450)
    
    with col2:
        st.subheader("📈 Høydeprofil")
        # Grafen får mer plass nå som risiko-grafen er borte
        st.area_chart(df.set_index('KM')['Høyde'], height=380)
        
    st.subheader("📋 Detaljert Veirapport")
    st.dataframe(df, use_container_width=True)
