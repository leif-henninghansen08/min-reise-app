import streamlit as st
import requests
import folium
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. OPPSETT ---
st.set_page_config(page_title="SikkerTur Stabil", page_icon="🚗", layout="wide")

# --- 2. SIKKER HENTING AV API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except Exception:
    st.error("API-nøkkel mangler i Secrets!")
    st.stop()

# --- 3. INITIALISER MINNE ---
# Vi bruker disse for å lagre resultatene permanent i denne økten
if "kart_html" not in st.session_state:
    st.session_state.kart_html = None
if "tabell_data" not in st.session_state:
    st.session_state.tabell_data = None
if "reise_tekst" not in st.session_state:
    st.session_state.reise_tekst = None

# --- 4. FUNKSJONER ---
def hent_stedsnavn(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality|administrative_area_level_2"
    try:
        res = requests.get(url).json()
        return res['results'][0]['address_components'][0]['long_name'] if res['status'] == 'OK' else "Vei"
    except: return "Norge"

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/30.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"
    try:
        r = requests.get(url, headers=headers).json()
        v = min(r['properties']['timeseries'], key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '+00:00')) - tid.replace(tzinfo=None)).total_seconds()))
        d = v['data']['instant']['details']
        return d['air_temperature'], v['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0), d['wind_speed']
    except: return 0, 0, 0

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("Planlegg tur")
    fra = st.text_input("Fra:", "Sandnessjøen")
    til = st.text_input("Til:", "Trondheim")
    dato = st.date_input("Dato:", datetime.now())
    tid_v = st.time_input("Tid:", datetime.now())
    
    # Knappen trigger kun selve beregningen
    start_knapp = st.button("Start Analyse", type="primary")

# --- 6. LOGIKK VED TRYKK PÅ KNAPP ---
if start_knapp:
    with st.spinner('Beregner rute og vær...'):
        avreise_dt = datetime.combine(dato, tid_v)
        url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        res = requests.get(url).json()

        if res['status'] == 'OK':
            leg = res['routes'][0]['legs'][0]
            st.session_state.reise_tekst = f"**Rute:** {leg['distance']['text']} | **Tid:** {leg['duration']['text']}"
            
            # Lag kart sentrert på start
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            
            temp_data = []
            akk_m, akk_s, neste_km = 0, 0, 0

            for step in leg['steps']:
                akk_m += step['distance']['value']
                akk_s += step['duration']['value']
                curr_km = akk_m / 1000

                if curr_km >= neste_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_s)
                    lat, lon = step['end_location']['lat'], step['end_location']['lng']
                    temp, nb, vind = hent_vaer(lat, lon, ankomst)
                    sted = hent_stedsnavn(lat, lon)
                    
                    # Fargekode basert på temp (is-fare)
                    farge = 'red' if -2 <= temp <= 1 else 'green'
                    
                    folium.Marker(
                        [lat, lon],
                        popup=f"{sted}: {temp}°C",
                        icon=folium.Icon(color=farge)
                    ).add_to(m)
                    
                    temp_data.append({"KM": round(curr_km), "Tid": ankomst.strftime('%H:%M'), "Sted": sted, "Temp": f"{temp}°C"})
                    neste_km += 100

            # LAGRE TIL SESSION STATE (Viktig!)
            st.session_state.tabell_data = temp_data
            st.session_state.kart_html = m._repr_html_()
        else:
            st.error("Kunne ikke finne rute.")

# --- 7. VISNING (Alltid utenfor knappen) ---
# Dette feltet tegnes kun hvis det finnes data i minnet
if st.session_state.kart_html:
    st.markdown(st.session_state.reise_tekst)
    
    # Vi legger kartet inn i en "container" for å fiksere det
    with st.container():
        components.html(st.session_state.kart_html, height=500, scrolling=False)
    
    st.subheader("Etappeoversikt")
    st.dataframe(st.session_state.tabell_data, use_container_width=True)
else:
    st.info("Velg destinasjoner i menyen til venstre og trykk 'Start Analyse'.")
