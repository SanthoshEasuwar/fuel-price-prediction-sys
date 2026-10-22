
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from services.auth_service import render_account_sidebar, require_user
from services.ui import apply_fuel_theme

# --------------------------------------------------
# 1. PAGE CONFIGURATION
# --------------------------------------------------
st.set_page_config(
    page_title="Model Evaluation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_fuel_theme()
require_user()
render_account_sidebar("model_evaluation")

st.title("📊 Model Evaluation")
st.write(
    "Evaluate next-day fuel-price estimates using the recorded "
    "test results from the project."
)

# --------------------------------------------------
# 2. PROJECT PATHS
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

REPORT_PATH = MODELS_DIR / "final_evaluation_report_v1.csv"
COMPARISON_PATH = MODELS_DIR / "model_comparison_v3.csv"
YEARLY_PATH = MODELS_DIR / "persistence_by_year_v1.csv"

# --------------------------------------------------
# 3. HELPER FUNCTIONS
# --------------------------------------------------
@st.cache_data
def load_csv(file_path):
    return pd.read_csv(file_path)


def find_column(data, candidates):
    """Find a column using case-insensitive name matching."""
    lookup = {column.lower(): column for column in data.columns}

    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]

    return None


def show_csv_preview(path, title):
    """Display a CSV when it exists."""
    if path.exists():
        data = load_csv(str(path))
        st.subheader(title)
        st.dataframe(data, width="stretch", hide_index=True)
        return data

    st.info(f"File not found: {path.name}")
    return None


# --------------------------------------------------
# 4. EVALUATION EXPLANATION
# --------------------------------------------------
with st.expander("What do these metrics mean?"):
    st.markdown(
        """
        - **MAE:** Mean Absolute Error. The average absolute difference
          between the predicted and actual price.
        - **RMSE:** Root Mean Squared Error. Penalizes large errors
          more strongly than MAE.
        - **Persistence baseline:** Uses the latest recorded price
          as tomorrow's estimate.
        - **Test set:** A chronological period held out to evaluate
          performance on later observations.
        """
    )

# --------------------------------------------------
# 5. LOAD FINAL REPORT
# --------------------------------------------------
st.header("Final Test Results")

if REPORT_PATH.exists():
    report = load_csv(str(REPORT_PATH))

    st.caption(
        "Values below are read from the saved final evaluation report. "
        "The report's exact column names and values are preserved."
    )

    st.dataframe(
        report,
        width="stretch",
        hide_index=True,
    )
else:
    st.warning(
        "The final evaluation report was not found. "
        "Copy final_evaluation_report_v1.csv into the models folder."
    )
    report = None

# --------------------------------------------------
# 6. MODEL COMPARISON
# --------------------------------------------------
st.divider()
st.header("Model Comparison")

if COMPARISON_PATH.exists():
    comparison = load_csv(str(COMPARISON_PATH))

    st.dataframe(
        comparison,
        width="stretch",
        hide_index=True,
    )

    st.download_button(
        "Download model comparison CSV",
        data=comparison.to_csv(index=False).encode("utf-8"),
        file_name="model_comparison_v3.csv",
        mime="text/csv",
    )

    # Try to find metric columns for a chart.
    model_col = find_column(
        comparison,
        ["model", "model_name", "approach", "estimator"],
    )
    mae_col = find_column(
        comparison,
        ["mae", "test_mae", "petrol_mae", "diesel_mae"],
    )

    if model_col and mae_col:
        chart_data = comparison[[model_col, mae_col]].copy()
        chart_data[mae_col] = pd.to_numeric(
            chart_data[mae_col], errors="coerce"
        )
        chart_data = chart_data.dropna()

        if not chart_data.empty:
            fig = px.bar(
                chart_data,
                x=model_col,
                y=mae_col,
                title="Model Comparison: Available MAE Values",
                labels={
                    model_col: "Model",
                    mae_col: "MAE (₹ per litre)",
                },
            )
            st.plotly_chart(fig, width="stretch")
else:
    st.warning(
        "model_comparison_v3.csv was not found in the models folder."
    )

# --------------------------------------------------
# 7. YEARLY BASELINE PERFORMANCE
# --------------------------------------------------
st.divider()
st.header("Persistence Baseline by Year")

if YEARLY_PATH.exists():
    yearly = load_csv(str(YEARLY_PATH))

    st.dataframe(
        yearly,
        width="stretch",
        hide_index=True,
    )

    st.download_button(
        "Download yearly baseline results",
        data=yearly.to_csv(index=False).encode("utf-8"),
        file_name="persistence_by_year_v1.csv",
        mime="text/csv",
    )
else:
    st.info(
        "persistence_by_year_v1.csv was not found. "
        "The yearly analysis is optional."
    )

# --------------------------------------------------
# 8. INTERPRETATION
# --------------------------------------------------
st.divider()
st.header("Interpretation and Limitations")

st.markdown(
    """
    **Current finding:** In the experiments completed so far, the
    persistence baseline performed better overall than the tested
    Random Forest model on the reported test period.

    **Why this matters:** Fuel prices often remain unchanged for
    multiple consecutive days. A model that predicts a price revision
    too frequently can perform worse than simply carrying forward
    the last observed price.

    **Limitations:**
    - A low overall error does not necessarily mean the model can
      predict the timing of a price revision.
    - Price revisions are relatively rare in recent portions of
      this dataset, so results should be interpreted in that context.
    - Historical data is not live data.
    - These results do not establish that machine learning improves
      on the baseline.
    - New models should be evaluated on a chronological holdout
      using the same target definition and test period.
    """
)

st.caption(
    "All metrics shown above come from saved project CSV files. "
    "This page does not retrain models or generate new evaluation results."
)
