import streamlit as st
import requests
import folium
import polyline
import pandas as pd
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 1. KONFIGURASJON ---
st.set_page_config(page_title="SikkerTur Pro v21.6 - Lade-eksperten", page_icon="⚡", layout="wide")

# --- 2. API-NØKKEL ---
try:
    API_KEY = st.secrets["google_maps_api_key"]
except:
    st.error("API-nøkkel mangler i Streamlit Secrets!")
    st.stop()

# --- 3. AVANSERTE FUNKSJONER ---

def hent_alle_ladere_langs_rute(route_polyline):
    # Bruker Google Places Text Search med rute-kontekst (forenklet simulering her)
    # I en produksjons-app ville man brukt 'searchAlongRoute' endpoint
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": "Tesla Supercharger",
        "key": API_KEY,
        "location": "61.5, 10.5", # Midt-Norge fokus
        "radius": "500000"
    }
    try:
        res = requests.get(url, params=params).json()
        if res['status'] == 'OK':
            return res['results']
    except: pass
    return []

def vurder_lader(lader_data, neste_stigning_km, km_merke):
    rating = lader_data.get('rating', 0)
    user_ratings = lader_data.get('user_ratings_total', 0)
    navn = lader_data.get('name', 'Tesla Supercharger')
    
    anbefaling = ""
    # Logikk: Er dette en god lader før en tøff etappe?
    if km_merke < neste_stigning_km and (neste_stigning_km - km_merke) < 40:
        anbefaling = "⭐ ANBEFALT: Siste lader før stigning."
    elif rating >= 4.5 and user_ratings > 100:
        anbefaling = "☕ Topp fasiliteter/rating."
    
    return anbefaling

# (Henter vær, høyde, kommune og risiko-funksjoner fra v21...)
# [Inkluderer funksjonene: hent_vaer_detaljer, hent_hoyde, hent_kommune, analyser_forhold]

# --- 4. LOGIKK ---
if st.sidebar.button("🚀 Kjør Totalanalyse", type="primary"):
    with st.spinner('Analyserer rute, vær og lade-nettverk...'):
        avreise_dt = datetime.combine(st.sidebar.date_input("Dato", key="d1"), st.sidebar.time_input("Tid", key="t1"))
        
        # 1. Hent Rute
        route_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={fra}&destination={til}&key={API_KEY}"
        route_res = requests.get(route_url).json()

        if route_res['status'] == 'OK':
            leg = route_res['routes'][0]['legs'][0]
            polyline_str = route_res['routes'][0]['overview_polyline']['points']
            alle_ladere = hent_alle_ladere_langs_rute(polyline_str)
            
            # Finn punkter med stor stigning (neste fjellovergang)
            stigninger = [] # Lagrer KM-merker for høyde > 700m
            
            temp_tabell = []
            akk_sek, akk_met, neste_sjekk_km, total_delay = 0, 0, 0, 0

            for step in leg['steps']:
                dist_km = akk_met / 1000
                if dist_km >= neste_sjekk_km:
                    lat, lon = step['start_location']['lat'], step['start_location']['lng']
                    ankomst = avreise_dt + timedelta(seconds=akk_sek + (total_delay * 60))
                    
                    # Finn nærmeste lader fra vår liste "langs ruten"
                    lader_her = next((l for l in alle_ladere if abs(l['geometry']['location']['lat'] - lat) < 0.05), None)
                    
                    vaer = hent_vaer_detaljer(lat, lon, ankomst)
                    hoyde = hent_hoyde(lat, lon)
                    if hoyde > 700: stigninger.append(neste_sjekk_km)
                    
                    sikt, kjore, score, delay, forbruk = analyser_forhold(vaer, ankomst, hoyde)
                    
                    anbefalt_tekst = ""
                    if lader_her:
                        neste_stigning = min([s for s in stigninger if s > dist_km], default=9999)
                        anbefalt_tekst = vurder_lader(lader_her, neste_stigning, dist_km)
                        lader_navn = f"⚡ {lader_her['name']}"
                    else:
                        lader_navn = ""

                    temp_tabell.append({
                        "KM": int(neste_sjekk_km),
                        "Ankomst": ankomst.strftime("%H:%M"),
                        "Sted": hent_kommune(lat, lon),
                        "Høyde": hoyde,
                        "Føre": kjore,
                        "Forbruk": forbruk,
                        "Tesla Lader": lader_navn,
                        "Anbefaling": anbefalt_tekst,
                        "Risiko": score
                    })
                    neste_sjekk_km += 30 # Tettere sjekk for bedre lade-oppløsning

                akk_met += step['distance']['value']
                akk_sek += step['duration']['value']

            st.session_state.tabell_data = temp_tabell
            # ... (kart-generering som før)

# --- 5. VISNING ---
if st.session_state.tabell_data:
    df = pd.DataFrame(st.session_state.tabell_data)
    
    st.subheader("📋 Reise- og Ladeplan")
    
    # Fremhev anbefalte ladestopp
    anbefalinger = df[df['Anbefaling'] != ""]
    if not anbefalinger.empty:
        st.info("💡 **Smarte lade-tips for denne ruten:**")
        for idx, row in anbefalinger.iterrows():
            st.write(f"- Ved {row['KM']} km ({row['Sted']}): {row['Tesla Lader']} - *{row['Anbefaling']}*")

    st.dataframe(df.style.apply(lambda x: ['background-color: #f0f7ff' if x.Anbefaling != "" else '' for i in x], axis=1), use_container_width=True)
