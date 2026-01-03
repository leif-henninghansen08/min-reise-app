import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta

# --- APP KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur - Reiseplanlegger", layout="wide")
st.title("🛡️ SikkerTur: Risikoanalyse & Elbil-lading")

# --- DIN API NØKKEL ---
API_KEY = "AIzaSyBk2ZqtmrPjWeZc6eZiIPyZ5p4VuWsc1ww"

# --- SIDEBAR (INPUT) ---
with st.sidebar:
    st.header("Reiseinformasjon")
    fra = st.text_input("Reis fra", "Sandnessjøen")
    til = st.text_input("Reis til", "Trondheim")
    dato = st.date_input("Dato", datetime.now())
    tid = st.time_input("Tidspunkt", datetime.now())
    knapp = st.button("Planlegg min reise")

# --- HJELPEFUNKSJONER (Samme logikk som før) ---
def hent_data(start, slutt, dt):
    unix_tid = int(datetime.combine(dato, tid).timestamp())
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={start}&destination={slutt}&departure_time={unix_tid}&key={API_KEY}&language=no"
    return requests.get(url).json()

def beregn_risiko(temp, nb):
    score = 0
    if temp <= 0: score += 5
    if nb > 0: score += 3
    status = "🔴" if score >= 7 else "🟡" if score >= 4 else "🟢"
    return score, status

# --- HOVEDLOGIKK ---
if knapp:
    res = hent_data(fra, til, tid)
    
    if res['status'] == 'OK':
        leg = res['routes'][0]['legs'][0]
        st.success(f"Rute funnet! Total distanse: {leg['distance']['text']}")
        
        # Lag kartet
        m = folium.Map(location=[65, 12], zoom_start=5)
        
        # Vi sjekker punkter hver 100km
        akk_m = 0
        neste_km = 0
        tabell_data = []

        for step in leg['steps']:
            akk_m += step['distance']['value']
            curr_km = akk_m / 1000
            
            if curr_km >= neste_km:
                lat, lon = step['end_location']['lat'], step['end_location']['lng']
                
                # Her ville vi kalt de andre funksjonene (Vær, Kamera, Lading)
                # For eksempelets skyld bruker vi faste verdier på været
                score, status = beregn_risiko(-1, 0.5) 
                
                # Legg til i kart
                folium.Marker(
                    [lat, lon],
                    popup=f"Punkt {round(curr_km)}km",
                    icon=folium.Icon(color="red" if score >= 7 else "green")
                ).add_to(m)
                
                tabell_data.append({
                    "KM": round(curr_km),
                    "Status": status,
                    "Risiko": f"{score}/10"
                })
                neste_km += 100

        # Vis kartet i appen
        st_folium(m, width=700, height=500)
        
        # Vis tabellen under kartet
        st.table(tabell_data)
    else:
        st.error("Kunne ikke finne ruten. Sjekk stedsnavn.")

