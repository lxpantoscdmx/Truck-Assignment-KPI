# OTTA - Optimized Trucking Assignment Audit (v4.6_stable_plus)

import streamlit as st
import pandas as pd
import datetime
import matplotlib.pyplot as plt
import base64
from io import BytesIO

PRIMARY_COLOR = "#A50034"

st.set_page_config(page_title="OTTA - Optimized Trucking Assignment Audit", layout="wide")
st.title("OTTA - Optimized Trucking Assignment Audit (v4.6_stable_plus)")

st.sidebar.header("Upload Files")
shipment_file = st.sidebar.file_uploader("Upload Shipment Data", type=["csv", "xlsx"])
tariff_file = st.sidebar.file_uploader("Upload Tariff Data", type=["xlsx"])
mylg_mapping_file = st.sidebar.file_uploader("Upload MYLG Mapping (optional)", type=["csv"])
exclusion_file = st.sidebar.file_uploader("Upload Exclusion Config", type=["csv"])

percent_threshold = st.sidebar.slider("Top % Threshold for Tariff", 10, 50, 30)
start_date = st.sidebar.date_input("Start Date", datetime.date(2025, 1, 1))
end_date = st.sidebar.date_input("End Date", datetime.date.today())

if shipment_file and tariff_file and exclusion_file:
    shipment_df = pd.read_excel(shipment_file) if shipment_file.name.endswith("xlsx") else pd.read_csv(shipment_file, encoding="latin1")
    tariff_df = pd.read_excel(tariff_file, header=0)
    tariff_df.columns = tariff_df.columns.str.strip()
    exclusion_df = pd.read_csv(exclusion_file)

    if mylg_mapping_file:
        mylg_mapping_df = pd.read_csv(mylg_mapping_file)
        shipment_df = shipment_df.merge(mylg_mapping_df, on="LOAD_ID", how="left")
        shipment_df['CARRIER_CODE'] = shipment_df.apply(
            lambda x: x['REAL_CARRIER_CODE'] if pd.notnull(x.get('REAL_CARRIER_CODE')) and x['CARRIER_CODE'] == 'MYLG' else x['CARRIER_CODE'], axis=1)

    shipment_df = shipment_df[shipment_df['CARRIER_CODE'] != 'MYLG']
    shipment_df['SHIP_DATE'] = pd.to_datetime(shipment_df['SHIP_DATE'], errors='coerce')
    shipment_df = shipment_df[(shipment_df['SHIP_DATE'] >= pd.to_datetime(start_date)) & (shipment_df['SHIP_DATE'] <= pd.to_datetime(end_date))]

    zip_to_wh = {'54602': 'N2A', '54605': 'N2E', '66643': 'NBN'}
    if 'SHIP_FROM_ZIP' in shipment_df.columns:
        shipment_df['WH_CODE'] = shipment_df['SHIP_FROM_ZIP'].astype(str).map(zip_to_wh)
    else:
        shipment_df['WH_CODE'] = shipment_df['DC_POSTAL'].astype(str).map(zip_to_wh)

    for _, row in exclusion_df.iterrows():
        shipment_df = shipment_df[shipment_df[row['COLUMN']] != row['EXCLUDE_VALUE']]

    shipment_df['GROUP'] = shipment_df['TRANSPORT_MODE'].apply(lambda x: ''.join(filter(str.isalpha, str(x))) if pd.notnull(x) else x)
    shipment_df['POSTALCODE'] = shipment_df['POSTALCODE'].astype(str).str.zfill(5)
    shipment_df['TRUCK_COUNT'] = shipment_df['TRANSPORT_MODE'].str.extract(r'(\d+)$').fillna(1).astype(int)

    base_df = shipment_df.drop_duplicates('LOAD_ID')[['LOAD_ID', 'WH_CODE', 'GROUP', 'POSTALCODE', 'TRUCK_COUNT']].copy()

    def match_rate(row, rate_col):
        if pd.isna(row['WH_CODE']) or pd.isna(row['GROUP']) or pd.isna(row['POSTALCODE']):
            return None
        match = tariff_df[
            (tariff_df['ORIGIN'] == row['WH_CODE']) &
            (tariff_df['GROUP'] == row['GROUP']) &
            (tariff_df['POSTAL CODE FROM'] <= int(row['POSTALCODE'])) &
            (tariff_df['POSTAL CODE TO'] >= int(row['POSTALCODE']))
        ]
        return match[rate_col].values[0] if not match.empty else None

    base_df['RATE_2024'] = base_df.apply(lambda x: match_rate(x, '2024 RATE'), axis=1)
    base_df['RATE_2025'] = base_df.apply(lambda x: match_rate(x, '2025 TARGET'), axis=1)

    estimate_sum = shipment_df.groupby('LOAD_ID')['SHIPMENT_ESTIMATE'].sum().reset_index(name='ACTUAL_COST')
    load_df = base_df.merge(estimate_sum, on='LOAD_ID', how='left')
    load_df['RATE_2024_TOTAL'] = load_df['RATE_2024'] * load_df['TRUCK_COUNT']
    load_df['RATE_2025_TOTAL'] = load_df['RATE_2025'] * load_df['TRUCK_COUNT']
    load_df['GAP_2024'] = load_df['ACTUAL_COST'] - load_df['RATE_2024_TOTAL']
    load_df['GAP_2025'] = load_df['ACTUAL_COST'] - load_df['RATE_2025_TOTAL']
    load_df['USE_TARGET_SUCCESS'] = load_df['ACTUAL_COST'] <= load_df['RATE_2025_TOTAL']

    total = load_df.shape[0]
    success = load_df['USE_TARGET_SUCCESS'].sum()
    failure = total - success
    actual_cost = load_df['ACTUAL_COST'].sum()
    projected_2024 = load_df['RATE_2024_TOTAL'].sum()
    projected_2025 = load_df['RATE_2025_TOTAL'].sum()
    gap_2024 = actual_cost - projected_2024
    gap_2025 = actual_cost - projected_2025

    def mxn(x): return f"{int(round(x)):,} MXN"
    def percent(x): return f"{x * 100:.1f}%"

    st.metric("Total Loads", total)
    st.metric("Success", int(success))
    st.metric("Failure", int(failure))
    st.metric("Success Rate (%)", percent(success / total))
    st.metric("Actual Cost", mxn(actual_cost))
    st.metric("2024 Projected Cost", mxn(projected_2024))
    st.metric("2025 Target Cost", mxn(projected_2025))
    st.metric("GAP vs 2024", mxn(gap_2024))
    st.metric("GAP vs 2025", mxn(gap_2025))

    st.subheader("📊 KPI Summary by WH + State")

    # Top 3 Carriers per State
    
    kpi = load_df.merge(shipment_df[['LOAD_ID', 'STATE']], on='LOAD_ID', how='left')
    summary = kpi.groupby(['WH_CODE', 'STATE']).agg(
        Loads=('LOAD_ID', 'count'),
        Success=('USE_TARGET_SUCCESS', 'sum'),
        Actual_Cost=('ACTUAL_COST', 'sum'),
        Target_Cost=('RATE_2025_TOTAL', 'sum'),
        GAP=('GAP_2025', 'sum')
    ).reset_index()
    summary['Failures'] = summary['Loads'] - summary['Success']
    summary['Success Rate (%)'] = summary['Success'] / summary['Loads'] * 100
    summary['Success Rate (%)'] = summary['Success Rate (%)'].map(lambda x: round(x, 1))
    summary['Actual_Cost'] = summary['Actual_Cost'].map(lambda x: f"{int(round(x)):,}")
    summary['Target_Cost'] = summary['Target_Cost'].map(lambda x: f"{int(round(x)):,}")
    summary['GAP'] = summary['GAP'].map(lambda x: f"{int(round(x)):,}")
    st.dataframe(summary)

    # 출발지, 도착지 기준 Top 3 운송사 (Load 수 및 비중)
    st.subheader("🚛 Top 3 Carriers by Origin-Destination Pair")
    od_carriers = shipment_df.groupby(['WH_CODE', 'STATE', 'CARRIER_CODE']).size().reset_index(name='Loads')
    total_od = od_carriers.groupby(['WH_CODE', 'STATE'])['Loads'].transform('sum')
    od_carriers['Percent'] = od_carriers['Loads'] / total_od * 100
    top3_od = od_carriers.sort_values(['WH_CODE', 'STATE', 'Loads'], ascending=[True, True, False])
    top3_od = top3_od.groupby(['WH_CODE', 'STATE']).head(3)
    top3_od['Percent'] = top3_od['Percent'].map(lambda x: f"{x:.1f}%")
    st.dataframe(top3_od)
    shipment_df['Week'] = shipment_df['SHIP_DATE'].dt.strftime('%Y-%U')
    trend = shipment_df.merge(load_df[['LOAD_ID', 'USE_TARGET_SUCCESS']], on='LOAD_ID')
    weekly = trend.groupby('Week')['USE_TARGET_SUCCESS'].agg(['sum', 'count'])
    weekly['Success Rate (%)'] = (weekly['sum'] / weekly['count']) * 100


    st.markdown("<h3 style='display: flex; align-items: center;'><img src='https://img.icons8.com/color/48/000000/combo-chart.png' style='height:24px;margin-right:8px;'/>Weekly Trend</h3>", unsafe_allow_html=True)


    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(weekly.index, weekly['Success Rate (%)'], marker='o', color=PRIMARY_COLOR)
    for i, (week, value) in enumerate(weekly['Success Rate (%)'].items()):
        ax.text(i, value + 1, f"{value:.1f}%", ha='center', fontsize=8)
    ax.set_title("Weekly Success Rate")
    ax.set_ylabel("Success Rate (%)")
    ax.set_xlabel("Week")
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)

    st.subheader("📥 Download KPI Report")
    def to_html():
        summary_html = summary.to_html(index=False)
        return f"""
        <html><body>
        <h2>OTTA KPI Report</h2>
        <p><strong>Total:</strong> {total}, <strong>Success:</strong> {success}, <strong>Failure:</strong> {failure}, <strong>Success Rate:</strong> {percent(success / total)}</p>
        <p><strong>Actual Cost:</strong> {mxn(actual_cost)}</p>
        <p><strong>2024 Projected Cost:</strong> {mxn(projected_2024)}</p>
        <p><strong>2025 Target Cost:</strong> {mxn(projected_2025)}</p>
        <p><strong>GAP vs 2024:</strong> {mxn(gap_2024)}</p>
        <p><strong>GAP vs 2025:</strong> {mxn(gap_2025)}</p>
        <h3>Summary by WH + State</h3>
        {summary_html}
        </body></html>
        """

    html = to_html()
    st.download_button("Download HTML Report", html, file_name="otta_kpi_report.html", mime='text/html')

else:
    st.warning("Please upload Shipment Data, Tariff Data and Exclusion Config.")
