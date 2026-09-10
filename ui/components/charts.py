import plotly.graph_objects as go


def captaincy_bar(candidates):
    names = [c["name"] for c in candidates]
    scores = [c["captaincy_score"] for c in candidates]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=scores, y=names, orientation="h",
        marker_color="#00ff87", name="Captaincy score",
        text=[f"{s:.2f}" for s in scores], textposition="outside",
    ))
    fig.update_layout(
        height=380, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Captaincy score",
        yaxis=dict(autorange="reversed"), showlegend=False,
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        font=dict(color="#ddd"),
    )
    return fig


def mae_over_time(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["gw"], y=df["mae"], mode="lines+markers",
                             name="MAE", line=dict(color="#00ff87", width=3)))
    fig.add_trace(go.Scatter(x=df["gw"], y=df["rmse"], mode="lines+markers",
                             name="RMSE", line=dict(color="#04f5ff",
                                                     width=3, dash="dot")))
    fig.update_layout(height=320, xaxis_title="Gameweek", yaxis_title="Error",
                      plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                      font=dict(color="#ddd"))
    return fig


def calibration_plot(buckets):
    preds = [b["predicted"] for b in buckets]
    actuals = [b["actual"] for b in buckets]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                             name="Perfect", line=dict(color="#888", dash="dash")))
    fig.add_trace(go.Scatter(x=preds, y=actuals, mode="markers+lines",
                             name="Model",
                             marker=dict(size=12, color="#00ff87")))
    fig.update_layout(height=380, xaxis_title="Predicted",
                      yaxis_title="Actual",
                      plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                      font=dict(color="#ddd"))
    return fig