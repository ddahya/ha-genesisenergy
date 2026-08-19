# Genesis Energy Integration for Home Assistant (Beta)

[![hacs_badge](https://img.shields.io/badge/HACS-Beta-orange.svg)](https://github.com/hacs/default)

This is the **Beta / Testing branch** for the Genesis Energy (NZ) Home Assistant integration. 

> [!WARNING]
> **Beta Status — Untested Release:**  
> This version contains recent adaptations for Genesis Energy's new website and API changes. These changes are currently in testing.

## 🚀 Recent Beta Changes

### 1. New Genesis Website Compatibility & Sensor Restoration
* **Unified Bill Summary (`billSummaryV2`):** Updated billing sensors (`Electricity Used`, `Gas Used`, `Estimated Total`, `Total Used`) to use Genesis's new consolidated V2 endpoint.
* **Real-Time Eco Tracker (`/generationMix/realTime`):** Restored `Grid Generation Eco-Friendly` using the new live NZ grid mix endpoint.
* **Direct EV Rates (`/ev/rates/dayNight`):** Added direct polling for EV Day and Night tariff rates.
* **Updated Forecast Parser:** Defensively handles schema updates on `/v2/private/electricityForecast`.

### 2. Home Assistant Core Deprecation Fix
* Added `mean_type=StatisticMeanType.NONE` and `unit_class=None` to long-term statistics metadata, preventing deprecation warnings with the Home Assistant Recorder.

* ## 🛠️ In Progress 

* ⏳ **Power Shout Booking 
