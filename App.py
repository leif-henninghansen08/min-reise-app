import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v16", page_icon="🛡️", layout="wide")

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
    headers = {'User-Agent': 'SikkerTurApp/v16.0'}
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
            "skyer": details.get('cloud_area_fraction', 0),
            "symbol": summary
        }
    except: return {"temp": 0, "vind": 0, "skyer": 0, "symbol": "clearsky_day"}

def hent_hoyde(lat, lon):
    # Prøver en mer direkte tilnærming til Elevation API
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK' and res['results']:
            return int(res['results'][0]['elevation'])
        return 0
    except: return 0

def analyser_sikt_og_lys(vaer_data, ankomst_tid):
    sikt_grunn = "Klar sikt"
    lav_sikt_faktor = 0
    
    # Mørkekjøring (Mindre aggressiv vekting)
    time = ankomst_tid.hour
    er_morkt = time >= 17 or time <= 8
    
    symbol = vaer_data['symbol']
    skyer = vaer_data['skyer']
    
    if "fog" in symbol:
        sikt_grunn = "Tåke"; lav_sikt_faktor = 2
    elif "snow" in symbol:
        sikt_grunn = "Snøbyger"; lav_sikt_faktor = 2
    elif skyer > 95:
        sikt_grunn = "Tett skydekke"; lav_sikt_faktor = 1
    
    if er_morkt:
        sikt_grunn += " + Mørke"
        lav_sikt_faktor += 1
        
    return sikt_grunn, lav_sikt_faktor

def beregn_veiforhold_score(temp, vind, sikt_faktor):
    # Starter på 1 (perfekt)
    score = 1
    grunner = []
    
    # Isfare (Høyeste prioritet)
    if -1.5 <= temp <= 0.5: 
        score += 5; grunner.append("Isfare/Nullføre")
    elif temp < -1.5: 
        score += 3; grunner.append("Vinterføre")
    
    # Vind (Vektes etter styrke)
    if vind > 15: score += 3; grunner.append("Sterk vind")
    elif vind > 10: score += 1; grunner.append("Vind")
    
    # Sikt/Mørke (Vektes fra analyser_sikt_og_lys)
    score += sikt_faktor
    if sikt_faktor > 1: grunner.append("Dårlig sikt")
    elif sikt_faktor == 1: grunner.append("Mørkt")

    if not grunner: grunner.append("Gode forhold")
    return min(10, score), ", ".join(grunner)

# --- 4. SIDEBAR ---
st.sidebar.header("📍 SikkerTur Pro")
fra = st.sidebar.text_input("Fra:", value="Oslo", key="fra_in")
til = st.sidebar.text_input("Til:", value="Trondheim", key="til_in")
dato = st.sidebar.date_input("Dato:", value=datetime.now(), key="dato_in")
tid_v = st.sidebar.time_input("Tid:", value=datetime.now(), key="tid_in")
start_knapp = st.sidebar.button("🚀 Kjør Analyse", type="primary")

# --- 5. LOGIKK ---
if start_knapp:
    with st.spinner('Henter vær og veidata...'):
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
                    sikt_tekst, sikt_faktor = analyser_sikt_og_lys(vaer, ankomst)
                    score, forklaring = beregn_veiforhold_score(vaer['temp'], vaer['vind'], sikt_faktor)
                    
                    farge = "red" if score >= 7 else "orange" if score >= 4 else "green"
                    folium.Marker([lat, lon], popup=f"{score}/10: {forklaring}", icon=folium.Icon(color=farge)).add_to(m)
                    
                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Høyde (moh)": hoyde,
                        "Temp": f"{vaer['temp']}°C",
                        "Sikt": sikt_tekst,
                        "Risiko": score,
                        "Årsak": forklaring
                    })
                    neste_sjekk_km += 50

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"Distanse: {leg['distance']['text']} | Tid: {leg['duration']['text']}"

# --- 6. VISNING ---
if st.session_state.tabell_data:
    df = pd.DataFrame(st.session_state.tabell_data)
    
    # Risiko-oppsummering
    max_risk = df.loc[df['Risiko'].idxmax()]
    st.warning(f"⚠️ **Høyest risiko:** {max_risk['Risiko']}/10 ved {max_risk['KM']} km pga. {max_risk['Årsak']}.")

    col1, col2 = st.columns([2, 1])
    with col1:
        components.html(st.session_state.kart_html, height=500)
    with col2:
        st.write("📈 **Høydeprofil (moh)**")
        st.area_chart(df.set_index('KM')['Høyde (moh)'])
        st.write("⚠️ **Risikoprofil (0-10)**")
        st.line_chart(df.set_index('KM')['Risiko'])
        
    st.dataframe(df, use_container_width=True)
