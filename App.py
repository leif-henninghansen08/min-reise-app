import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v21.1", page_icon="🚗", layout="wide")

# --- 2. INITIALISERING OG API-NØKKEL ---
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "delay" not in st.session_state:
    st.session_state.delay = 0
if "orig_tid" not in st.session_state:
    st.session_state.orig_tid = ""

try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

# --- 3. HJELPEFUNKSJONER ---
def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v21.1'}
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

# --- 4. HOVEDLAYOUT OG LENKER ---
st.title("🚗 SikkerTur Pro")
st.markdown("### Eksterne sanntidstjenester")
col_link1, col_link2 = st.columns(2)
with col_link1:
    st.link_button("🏔️ Sjekk Fjelloverganger (Vegvesen)", "https://www.vegvesen.no/trafikkinformasjon/reiseinformasjon/fjelloverganger/", use_container_width=True)
with col_link2:
    st.link_button("📸 Webkamera langs veien", "https://www.vegvesen.no/trafikk", use_container_width=True)

st.divider()

# --- 5. SIDEBAR ---
st.sidebar.header("📍 Planlegg rute")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
dato = st.sidebar.date_input("Dato:", value=datetime.now())
tid_v = st.sidebar.time_input("Tid:", value=datetime.now())
start_knapp = st.sidebar.button("🚀 Kjør Totalanalyse", type="primary")

# --- 6. LOGIKK ---
if start_knapp:
    with st.spinner('Kjører avansert simulering...'):
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
                    sikt, kjore, score, delay, forbruk = analyser_forhold(vaer, ankomst, hoyde)
                    
                    total_delay += delay
                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Ankomst": ankomst.strftime("%H:%M"),
                        "Sted": kommune,
                        "Høyde": hoyde,
                        "Vær": f"{vaer['temp']}°C",
                        "Sikt": sikt,
                        "Kjøreforhold": kjore,
                        "Forbruk": forbruk,
                        "Risiko": score
                    })
                    neste_sjekk_km += 50

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.delay = total_delay
            st.session_state.orig_tid = leg['duration']['text']

# --- 7. VISNING ---
if st.session_state.get('tabell_data') is not None:
    df = pd.DataFrame(st.session_state.tabell_data)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Beregnet Forsinkelse", f"+{st.session_state.delay} min", "Pga. vær/føre")
    c2.metric("Total Reisetid", f"{st.session_state.orig_tid} (+{st.session_state.delay}m)")
    c3.metric("Status", "Analyse fullført")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("🗺️ Reisekart")
        components.html(st.session_state.kart_html, height=450)
    with col2:
        st.subheader("📈 Høydeprofil (moh)")
        st.area_chart(df.set_index('KM')['Høyde'], height=350)
        
    st.subheader("📋 Detaljert Veiplan")
    st.dataframe(df, use_container_width=True)
