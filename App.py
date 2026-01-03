import streamlit as st
import requests
import folium
from streamlit_folium import folium_static
from datetime import datetime, timedelta

# --- GRUNNLEGGENDE OPPSETT ---
st.set_page_config(page_title="SikkerTur Pro", page_icon="🛡️", layout="wide")

# --- DIN API-NØKKEL ---
API_KEY = "AIzaSyBk2ZqtmrPjWeZc6eZiIPyZ5p4VuWsc1ww"

# --- HJELPEFUNKSJONER ---
def hent_stedsnavn(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={API_KEY}&language=no&result_type=locality|administrative_area_level_2"
    try:
        res = requests.get(url).json()
        return res['results'][0]['address_components'][0]['long_name'] if res['status'] == 'OK' else "Langs veien"
    except: return "Norge"

def finn_ladestasjoner(lat, lon):
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=electric_vehicle_charging_station&key={API_KEY}"
    try:
        res = requests.get(url).json()
        return [p['name'] for p in res['results'][:3]] if res['status'] == 'OK' else []
    except: return []

def hent_vaer(lat, lon, tid):
    headers = {'User-Agent': 'SikkerTurApp/15.0'}
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat},{lon}"
    try:
        r = requests.get(url, headers=headers).json()
        # Finn vær nærmest ankomsttid
        v = min(r['properties']['timeseries'], key=lambda x: abs((datetime.fromisoformat(x['time'].replace('Z', '+00:00')) - tid.replace(tzinfo=None)).total_seconds()))
        d = v['data']['instant']['details']
        nb = v['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0)
        return d['air_temperature'], nb, d['wind_speed']
    except: return 0, 0, 0

def beregn_risiko(temp, nb, vind):
    score = 0
    if -1.5 <= temp <= 0.5: score += 5  # Nullføre er farligst
    elif temp < -1.5: score += 3        # Vanlig vinterføre
    if nb > 0.1: score += 3             # Nedbør/Snø
    if vind > 12: score += 2            # Mye vind
    score = min(score, 10)
    status = "🔴" if score >= 7 else "🟡" if score >= 4 else "🟢"
    return score, status

# --- APP-GRENSESNITT ---
st.title("🛡️ SikkerTur: Analyse for bil & elbil")

with st.sidebar:
    st.header("Turdetaljer")
    start = st.text_input("Reis fra:", "Sandnessjøen")
    slutt = st.text_input("Reis til:", "Trondheim")
    dato = st.date_input("Dato:", datetime.now())
    tid_valg = st.time_input("Tid:", datetime.now())
    st.divider()
    planlegg_knapp = st.button("Start Reiseanalyse", type="primary")

# --- KJØRING OG VISNING ---
if planlegg_knapp:
    with st.spinner('Henter veidata og beregner risiko...'):
        avreise_dt = datetime.combine(dato, tid_valg)
        url = f"https://maps.googleapis.com/maps/api/directions/json?origin={start}&destination={slutt}&departure_time={int(avreise_dt.timestamp())}&key={API_KEY}&language=no"
        res = requests.get(url).json()

        if res['status'] == 'OK':
            leg = res['routes'][0]['legs'][0]
            st.success(f"Analyse klar for turen mellom {start} og {slutt}")
            st.metric("Total avstand", leg['distance']['text'])
            
            # Opprett kartet
            m = folium.Map(location=[leg['start_location']['lat'], leg['start_location']['lng']], zoom_start=6)
            
            tur_data = []
            akk_m, akk_s, neste_km = 0, 0, 0

            # Gå gjennom ruten
            for step in leg['steps']:
                akk_m += step['distance']['value']
                akk_s += step['duration']['value']
                curr_km = akk_m / 1000

                if curr_km >= neste_km:
                    ankomst = avreise_dt + timedelta(seconds=akk_s)
                    lat, lon = step['end_location']['lat'], step['end_location']['lng']
                    
                    temp, nb, vind = hent_vaer(lat, lon, ankomst)
                    score, status = beregn_risiko(temp, nb, vind)
                    sted = hent_stedsnavn(lat, lon)
                    ladere = finn_ladestasjoner(lat, lon)
                    kamera = f"https://www.vegvesen.no/trafikk/kamera?lat={lat}&lon={lon}"
                    
                    # Kart-markør
                    farge = 'red' if score >= 7 else 'orange' if score >= 4 else 'green'
                    lader_str = f"<br>⚡ <b>Lading:</b> {', '.join(ladere)}" if ladere else ""
                    popup_html = f"<b>{sted}</b><br>Kl: {ankomst.strftime('%H:%M')}<br>Risiko: {score}/10 {status}<br>Temp: {temp}°C{lader_str}<br><a href='{kamera}' target='_blank'>Se Vegkamera</a>"
                    
                    folium.Marker(
                        [lat, lon],
                        popup=folium.Popup(popup_html, max_width=250),
                        icon=folium.Icon(color=farge, icon='info-sign')
                    ).add_to(m)
                    
                    tur_data.append({
                        "KM": round(curr_km),
                        "Tid": ankomst.strftime('%H:%M'),
                        "Sted": sted,
                        "Temp": f"{temp}°C",
                        "Risiko": f"{score}/10 {status}",
                        "Lading": ", ".join(ladere) if ladere else "-"
                    })
                    neste_km += 70 # Sjekker hver 70. km

            # VISNING AV KART (Denne er nå stabil)
            folium_static(m, width=700, height=500)
            
            # VISNING AV TABELL
            st.subheader("Detaljert oversikt")
            st.dataframe(tur_data, use_container_width=True)
        else:
            st.error("Kunne ikke beregne ruten. Sjekk stedsnavn eller API-nøkkel.")
else:
    st.info("Fyll inn detaljene i menyen til venstre og trykk 'Start Reiseanalyse' for å se kart og vær.")
