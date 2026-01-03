import streamlit as st
import requests
import folium
import polyline
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v11", page_icon="🚗", layout="wide")

# --- 2. API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Secrets!")
    st.stop()

# --- 3. INITIALISER MINNE ---
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "reise_info" not in st.session_state:
    st.session_state.reise_info = None

# --- 4. FUNKSJONER ---

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/v11.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        target_time = tid.replace(tzinfo=None)
        best_match = min(data['properties']['timeseries'], 
                         key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
        return best_match['data']['instant']['details']['air_temperature']
    except: return 0

def hent_hoyde(lat, lon):
    # Viktig: Elevation API må være aktivert i Google Cloud Console
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        if res['status'] == 'OK':
            return round(res['results'][0]['elevation'])
    except: return 0
    return 0

def hent_kommune(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no"
    try:
        res = requests.get(url, timeout=5).json()
        for result in res['results']:
            for component in result['address_components']:
                if "administrative_area_level_2" in component['types']:
                    return component['long_name']
    except: pass
    return "Ukjent kommune"

def beregn_veiforhold_score(temp):
    # Skala 0-10. 10 er verst (isfare).
    if temp is None: return 5
    if -1.5 <= temp <= 0.5: return 10  # Nullføre er farligst
    if temp < -1.5: return 7          # Stabilt kaldt
    if 0.5 < temp < 4: return 4       # Mulig slaps
    return 1                          # Gode forhold

# --- 5. SIDEBAR ---
# Ved å bruke st.sidebar utenfor 'if' blokker holder vi den stabil
st.sidebar.header("📍 Reiseplanlegger")
fra = st.sidebar.text_input("Fra:", value="Oslo", key="f")
til = st.sidebar.text_input("Til:", value="Trondheim", key="t")
dato = st.sidebar.date_input("Dato:", value=datetime.now(), key="d")
tid_v = st.sidebar.time_input("Tid:", value=datetime.now(), key="ti")
start_knapp = st.sidebar.button("🚀 Start Analyse", type="primary")

# --- 6. HOVEDLOGIKK ---
if start_knapp:
    with st.spinner('Henter data...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            route = route_res['routes'][0]
            leg = route['legs'][0]
            vei_punkter = polyline.decode(route['overview_polyline']['points'])
            
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="#2196F3", weight=5).add_to(m)
            m.fit_bounds(vei_punkter)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km = 0, 0, 0

            for step in leg['steps']:
                if (akk_met / 1000) >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sek)
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    temp = hent_vaer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    kommune = hent_kommune(lat, lon)
                    score = beregn_veiforhold_score(temp)
                    
                    farge = "red" if score >= 7 else "orange" if score >= 4 else "green"
                    
                    folium.Marker(
                        [lat, lon], 
                        popup=f"{kommune}: {score}/10",
                        icon=folium.Icon(color=farge)
                    ).add_to(m)
                    
                    temp_tabell.append({
                        "Distanse": f"{neste_sjekk_km} km",
                        "Kommune": kommune,
                        "Høyde": f"{hoyde} moh",
                        "Temp": f"{temp}°C",
                        "Veiforhold (0-10)": f"{score}/10"
                    })
                    neste_sjekk_km += 100

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            st.session_state.kart_html = m._repr_html_()
            st.session_state.reise_info = f"**Rute:** {leg['distance']['text']} | **Tid:** {leg['duration']['text']}"

# --- 7. VISNING ---
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_info)
    components.html(st.session_state.kart_html, height=500)
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
