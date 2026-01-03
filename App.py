import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v15", page_icon="🛡️", layout="wide")

# --- 2. API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

# --- 3. INITIALISER MINNE ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "reise_info" not in st.session_state:
    st.session_state.reise_info = None

# --- 4. FUNKSJONER ---

def hent_vaer_detaljer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v15.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        best_match = min(data['properties']['timeseries'], 
                         key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        
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
    # Oppdatert for å være mer robust mot "0"-feil
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat}%2C{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK' and len(res['results']) > 0:
            return round(res['results'][0]['elevation'])
        else:
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

def analyser_sikt_og_lys(vaer_data, ankomst_tid):
    sikt_grunn = "Klar sikt"
    lav_sikt = False
    
    # Sjekk mørke (Enkel sjekk: mellom 18:00 og 07:00 er det mørkt i Norge vinterstid)
    time = ankomst_tid.hour
    er_morkt = time >= 18 or time <= 7
    
    symbol = vaer_data['symbol']
    skyer = vaer_data['skyer']
    
    if "fog" in symbol:
        sikt_grunn = "Tåke"
        lav_sikt = True
    elif "snow" in symbol:
        sikt_grunn = "Snøbyger"
        lav_sikt = True
    elif "rain" in symbol and skyer > 90:
        sikt_grunn = "Kraftig regn"
        lav_sikt = True
    elif skyer > 95:
        sikt_grunn = "Lavt skydekke"
        lav_sikt = True
    
    if er_morkt:
        sikt_grunn += " + Mørkekjøring"
        lav_sikt = True
        
    return sikt_grunn, lav_sikt

def beregn_veiforhold_score(temp, vind, lav_sikt):
    score = 1
    grunner = []
    
    if -1.5 <= temp <= 0.5: 
        score = max(score, 10); grunner.append("Isfare (nullføre)")
    elif temp < -1.5: 
        score = max(score, 7); grunner.append("Vinterføre")
    
    if vind > 12: 
        score = min(10, score + 2); grunner.append("Vind")
    
    if lav_sikt: 
        score = min(10, score + 2); grunner.append("Redusert sikt")
        
    if not grunner: grunner.append("Gode forhold")
    return score, ", ".join(grunner)

# --- 5. SIDEBAR ---
st.sidebar.header("📍 Reiseplanlegger")
fra = st.sidebar.text_input("Fra:", value="Oslo")
til = st.sidebar.text_input("Til:", value="Trondheim")
dato = st.sidebar.date_input("Dato:", value=datetime.now())
tid_v = st.sidebar.time_input("Tid:", value=datetime.now())
start_knapp = st.sidebar.button("🚀 Start Totalanalyse", type="primary")

# --- 6. HOVEDLOGIKK ---
if start_knapp:
    with st.spinner('Kjører totalanalyse (Vær, Sikt, Høyde, Mørke)...'):
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
                    sikt_tekst, lav_sikt = analyser_sikt_og_lys(vaer, ankomst)
                    score, forklaring = beregn_veiforhold_score(vaer['temp'], vaer['vind'], lav_sikt)
                    
                    farge = "red" if score >= 8 else "orange" if score >= 5 else "green"
                    folium.Marker(
                        [lat, lon], 
                        popup=f"{kommune}: {score}/10\n{forklaring}",
                        icon=folium.Icon(color=farge, icon='cloud' if lav_sikt else 'info-sign')
                    ).add_to(m)
                    
                    temp_tabell.append({
                        "KM": neste_sjekk_km,
                        "Kommune": kommune,
                        "Høyde (moh)": hoyde,
                        "Temp": f"{vaer['temp']}°C",
                        "Sikt/Lys": sikt_tekst,
                        "Risiko": f"{score}/10",
                        "Årsak": forklaring
                    })
                    neste_sjekk_km += 50 # Sjekker hver 50. km for bedre graf

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"**Rute:** {leg['distance']['text']} | **Estimert tid:** {leg['duration']['text']}"

# --- 7. VISNING ---
if st.session_state.tabell_data:
    st.subheader("📊 Reiseoversikt")
    st.markdown(st.session_state.reise_info)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        components.html(st.session_state.kart_html, height=500)
    
    with col2:
        st.write("📈 **Høydeprofil og Risiko**")
        df = pd.DataFrame(st.session_state.tabell_data)
        st.line_chart(df.set_index('KM')['Høyde (moh)'])
        
    st.subheader("📋 Detaljert Logg")
    st.dataframe(df, use_container_width=True)
