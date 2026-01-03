import streamlit as st
import requests
import folium
import polyline
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro v9", page_icon="🚗", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
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
    headers = {'User-Agent': 'SikkerTurApp/v9.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={round(lat, 4)}&lon={round(lon, 4)}"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            target_time = tid.replace(tzinfo=None)
            best_match = min(data['properties']['timeseries'], 
                             key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '')) - target_time).total_seconds()))
            return best_match['data']['instant']['details']['air_temperature']
    except: return None

def hent_hoyde(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/elevation/json?locations={lat},{lon}&key={API_KEY}"
    try:
        res = requests.get(url).json()
        if res['status'] == 'OK':
            return round(res['results'][0]['elevation'])
    except: return 0

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("Planlegg reisen")
    fra = st.text_input("Fra:", "Oslo", key="input_fra")
    til = st.text_input("Til:", "Trondheim", key="input_til")
    dato = st.date_input("Dato", datetime.now(), key="input_dato")
    tid_v = st.time_input("Tid", datetime.now(), key="input_tid")
    start_knapp = st.button("Start Analyse", type="primary")

# --- 6. HOVEDLOGIKK ---
if start_knapp:
    with st.spinner('Analyserer rute, vær og høydeprofil...'):
        avreise_dt = datetime.combine(dato, tid_v)
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            route = route_res['routes'][0]
            leg = route['legs'][0]
            
            # Dekode vei for å følge den nøyaktig
            vei_punkter = polyline.decode(route['overview_polyline']['points'])
            m = folium.Map(location=vei_punkter[0], zoom_start=6)
            folium.PolyLine(vei_punkter, color="blue", weight=5, opacity=0.8).add_to(m)
            m.fit_bounds(vei_punkter)

            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km = 0, 0, 0

            for step in leg['steps']:
                if (akk_met / 1000) >= neste_sjekk_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_sek)
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    
                    temp = hent_vaer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    farge = "red" if temp is not None and temp <= 1 else "green"
                    
                    folium.Marker(
                        [lat, lon], 
                        popup=f"<b>{neste_sjekk_km} km</b><br>Høyde: {hoyde} moh<br>Temp: {temp}°C",
                        icon=folium.Icon(color=farge, icon='arrow-up' if hoyde > 500 else 'road')
                    ).add_to(m)
                    
                    temp_tabell.append({
                        "Distanse": f"{neste_sjekk_km} km",
                        "Tid": ankomst.strftime('%H:%M'),
                        "Høyde": f"{hoyde} moh",
                        "Temp": f"{temp}°C" if temp is not None else "N/A"
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
    
    # Viser tabellen med høydeprofil
    st.subheader("Veiprofil per 100 km")
    st.dataframe(st.session_state.tabell_data, use_container_width=True)

    # En liten visuell hjelp for å forstå høyde
    st.info("💡 Tips: Høyder over 500 meter over havet (moh) medfører ofte raskere værskifte og lavere temperaturer.")
