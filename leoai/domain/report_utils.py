import os


import plotly.graph_objs as go
from datetime import datetime, timedelta
  
# sample 
def generate_bar_chart():
    # TODO hiExample dummy data — replace with your real data
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    event_counts = [120, 98, 145, 110, 180, 220, 195]

    # Build bar chart
    fig = go.Figure(
        data=[
            go.Bar(
                x=event_counts,
                y=dates,
                orientation='h',  # horizontal bars: y = date, x = count
                text=event_counts,
                textposition="auto",
                marker=dict(
                    color="rgba(0,123,255,0.7)",
                    line=dict(color="rgba(0,123,255,1.0)", width=1.5)
                ),
            )
        ]
    )

    # Customize layout
    fig.update_layout(
        title="Profile Count by Date",
        xaxis_title="Profile Count",
        yaxis_title="Date (YYYY-MM-DD)",
        yaxis=dict(autorange="reversed"),  # make latest date on top
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=30, t=60, b=60),
        height=400,
    )

    # Export HTML (CDN = lightweight)
    final_answer = fig.to_html(full_html=True, include_plotlyjs='cdn')
    return final_answer

def generate_pie_chart():
    # Example dataset — replace with your actual location counts
    locations = ["Hanoi", "Ho Chi Minh City", "Da Nang", "Hue", "Can Tho"]
    profile_counts = [350, 500, 150, 80, 120]

    # Build pie chart
    fig = go.Figure(
        data=[
            go.Pie(
                labels=locations,
                values=profile_counts,
                textinfo="label+percent",
                hoverinfo="label+value+percent",
                marker=dict(
                    colors=[
                        "rgba(0,123,255,0.8)",
                        "rgba(40,167,69,0.8)",
                        "rgba(255,193,7,0.8)",
                        "rgba(220,53,69,0.8)",
                        "rgba(23,162,184,0.8)"
                    ],
                    line=dict(color="white", width=2)
                ),
                hole=0.3  # donut style looks cleaner
            )
        ]
    )

    # Customize layout
    fig.update_layout(
        title="Distribution of User Profiles by Location",
        legend_title="City",
        height=400,
        width=500,
        margin=dict(t=50, b=30, l=40, r=40),
        paper_bgcolor="white",
    )

    # Convert to HTML for embedding
    final_answer = fig.to_html(full_html=True, include_plotlyjs='cdn')
    return final_answer