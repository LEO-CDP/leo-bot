# **Travel Weather Knowledge Graph** 

 một KG kết hợp địa điểm + thời tiết + rủi ro thời tiết cực đoan để phục vụ lập kế hoạch du lịch.

Kiểu graph này thường gặp trong các hệ thống đề xuất du lịch, routing an toàn, cảnh báo rủi ro khí hậu, và xếp hạng điểm đến theo mức độ ảnh hưởng thời tiết.

Dưới đây là **thiết kế Knowledge Graph** hoàn chỉnh dựa trên schema bạn đã có (places + weather_data), thêm các entity liên quan, các loại quan hệ, ontology nhẹ, mapping qua ArangoDB hoặc PostgreSQL graph extension, và chiến lược cho semantic search + geospatial + rủi ro khí tượng.

---

## 🧭 **1. Mục tiêu của Knowledge Graph**

KG phải trả lời được những câu như:

* “Gợi ý điểm du lịch phù hợp trong tháng 3 ở miền Trung, tránh mưa bão.”
* “Khu vực nào đang chịu ảnh hưởng của bão, cần tránh đi vào cuối tuần này?”
* “Những địa điểm gần Đà Nẵng có thời tiết tương tự Nha Trang trong tuần này?”
* “Xếp hạng mức rủi ro thời tiết của các khu vực để đề xuất lịch trình an toàn.”

→ Điều này đòi hỏi KG kết hợp **geospatial → weather → semantic → temporal reasoning**.

---

## 🧱 **2. Các Node (Vertex Types)**

#### **1. Place**

Từ bảng `places`.
Thuộc tính quan trọng:

* id, name, address, geom (Point), region_id
* tags, category
* pluscode

#### **2. WeatherSnapshot**

Từ bảng `weather_data`. Một bản ghi thời tiết tại thời điểm T.

Thuộc tính:

* timestamp (trích từ original_data)
* temperature, precipitation, humidity, wind_speed, wind_direction
* severity_score (mức độ cực đoan)
* weather_embedding (vector 768)

#### **3. Region**

Từ `region_id` hoặc external dataset.
Ví dụ: Tây Bắc, Bắc Trung Bộ, Nam Trung Bộ…

#### **4. WeatherEvent (hiện tượng cực đoan)**

Sinh từ phân tích dữ liệu:

* Storm (bão)
* HeavyRain
* HeatWave
* FloodRiskZone (vùng rủi ro lũ)

Thuộc tính:

* level: 1–5
* affected_area (geom polygon)
* start_time, end_time

#### **5. TravelMonth**

Thời gian du lịch: 12 nodes đại diện cho các tháng trong năm
(dùng cho phân tích theo mùa).

---

## 🔗 **3. Các loại quan hệ (Edges)**

Dưới đây là xương sống KG.

#### **1. PLACE —has_weather→ WEATHER_SNAPSHOT**

```
(Place) -[:HAS_WEATHER_AT {timestamp}]→ (WeatherSnapshot)
```

Tạo bằng cách matching theo gần tọa độ (geospatial join):

* 100m–500m radius
* hoặc match exact nếu có mapping ID

#### **2. PLACE —nearby→ PLACE**

Dựa theo khoảng cách geospatial:

```
(Place)-[:NEARBY {km: distance}]→(Place)
```

Distance < 10km tùy nhu cầu.

#### **3. PLACE —in_region→ REGION**

Từ cột region_id.

#### **4. WEATHER_SNAPSHOT —similar_weather→ WEATHER_SNAPSHOT**

Dùng cosine similarity trên `weather_embedding`.

Quan trọng cho câu hỏi:
“Thời tiết ở đây giống ở đâu?”

#### **5. WEATHER_SNAPSHOT —indicates→ WEATHER_EVENT**

Ví dụ:

* wind_speed > 20m/s → Storm event
* rainfall > 100mm → HeavyRain
* temperature > 38°C → HeatWave

#### **6. REGION —risk_level→ WEATHER_EVENT**

Phục vụ cảnh báo khu vực.

#### **7. TRAVEL_MONTH —best_for→ PLACE**

Sinh tự động từ thống kê:
Ví dụ: tháng 3 phù hợp Hội An (ít mưa, không quá nóng).

---

## 🌦 **4. Ontology đơn giản (vocab)**

Dùng để đảm bảo mọi thứ đồng nhất:

**Classes:**

* Place
* WeatherSnapshot
* WeatherEvent
* Region
* TravelMonth

**Relations:**

* hasWeatherAt
* nearBy
* inRegion
* similarWeather
* indicates
* riskLevel
* bestFor

---

## 🗺 **5. Mapping schema SQL → Knowledge Graph**

#### **Place Node Construction**

* id → _key
* name, address, description
* geom → geoJSON (ArangoDB) hoặc ST_AsGeoJSON(PostGIS)

#### **Weather Node Construction**

Tạo mỗi snapshot như 1 node:

* id → _key
* location_name
* geog → geoJSON
* weather_embedding → vector store (Postgres)

#### **Edges**

Sinh bằng batch job hoặc event-driven pipeline:

* Place → Weather
* Weather → WeatherEvent
* Region → Place
* Place ↔ Place (geospatial proximity)
* WeatherSnapshot ↔ WeatherSnapshot (semantic similarity)

---

## 🧠 **6. Answering Travel Planning Queries**

#### **1. Tìm điểm du lịch trong 10km có thời tiết phù hợp**

```
START place = <your location>
MATCH (place)-[:NEARBY]->(p2)-[:HAS_WEATHER_AT]->(w)
WHERE w.precipitation < 20 AND w.temperature BETWEEN 20 AND 28
RETURN p2 ORDER BY w.severity_score ASC;
```

#### **2. Xếp hạng khu vực theo mức rủi ro bão/lũ**

```
MATCH (r:Region)-[:risk_level]->(e:WeatherEvent)
WHERE e.type IN ['Storm', 'Flood']
RETURN r, avg(e.level) as severity
ORDER BY severity DESC;
```

#### **3. Gợi ý nơi có thời tiết giống Đà Lạt**

```
Find weather_embedding of DaLat
Use pgvector -> top-k similarity
Then map ids → ArangoDB → get places → filter by travelMonth
```

---

## 🔥 **7. Rủi ro & thiên tai (Extreme Weather Risk Model)**

Mô hình KG này có sẵn chỗ để bạn cài risk scoring:

Severity Score =

* (precipitation * weight1)
* * (wind_speed * weight2)
* * (humidity anomalies * weight3)
* * (storm proximity * weight4)

Gắn vào WeatherSnapshot → rồi propagate theo quan hệ region / nearby.

---

## 🧩 **8. Toàn bộ KG này hoạt động thế nào?**

1. **PostGIS** xử lý geo → mapping Place ↔ Weather.
2. **pgvector** xử lý semantic → WeatherSimilarity.
3. **Knowledge Graph (ArangoDB hoặc Neo4j)** lưu tất cả node/edge.
4. **User query** → engine kết hợp:

   * semantic search (pgvector)
   * geospatial filter
   * graph traversal

→ Kết quả cuối là danh sách địa điểm **tối ưu** và **an toàn**.

---

Tuyệt — đi thẳng vào làm: mình sẽ đưa bạn một **thiết kế embedding model chuyên cho weather VN** (mô hình lai text + numeric + geo + time) và một **risk-ranking algorithm** (công thức, heuristics, cách aggregate lên region/place). Kèm theo **mã Python đầy đủ** cho preprocessing, huấn luyện (contrastive), inference và tính score rủi ro, cùng hướng lưu embedding vào Postgres/pgvector. Bạn có thể copy/paste và chạy trên cluster có GPU.

Mình giữ mọi thứ thực dụng và có thể triển khai ngay:

* embedding dim = **768** (tương thích với pipeline hiện tại)
* chiến lược huấn luyện: **contrastive + supervised** (positive pairs: snapshots cùng trạng thái thời tiết / gần về không gian & thời gian; negative: khác loại hoặc xa về địa lý)
* output: vector L2-normalized để dùng với pgvector/IVF/HNSW.

---

## 1) Ý tưởng model (tóm tắt)

* Input per snapshot: `{text_description, temperature, precipitation, wind_speed, humidity, pressure, latitude, longitude, timestamp, historical_precip_3d, elevation, soil_saturation_estimate, station_id}`
* Text encoder: dùng pretrained `sentence-transformers` (ví dụ `all-mpnet-base-v2`) để embed phần mô tả (`weather_text`) nếu có.
* Numeric encoder: chuẩn hoá numeric features → MLP (2 layer) → dense vector (dim 256).
* Geo/time encoder: encode cyclical time features (month, day_of_year, hour) + sin/cos lat/lon transform or learnable positional embedding → MLP (dim 128).
* Fusion: concat [text_emb(384)?, numeric(256), geo_time(128)] → projection MLP → 768-d → L2 normalize.
* Loss: **NT-Xent (contrastive)** với temperature τ; k positives per anchor (data augmentation: add noise to numeric, drop some text tokens, shift timestamp ±1 day). Nếu có labels (e.g., event type severity), add classification head + cross-entropy as auxiliary loss.

---

## 2) Preprocessing (chi tiết)

* Extract from `weather_data.original_data`: timestamp, main weather description, precip(mm), wind m/s, temp, humidity, pressure.
* Compute derived features:

  * `precip_1h`, `precip_24h`, `precip_72h` (backfill from timeseries)
  * `antecedent_rain_index = precip_72h * alpha + precip_24h * beta`
  * `distance_to_coast` (from geom)
  * `elevation` (external DEM lookup) — nếu không có, fallback 0.
  * `soil_saturation_estimate` (heuristic from antecedent_rain + local landcover)
* Normalize numerics with RobustScaler or StandardScaler fitted on training set.
* Produce `weather_text` from `original_data` summary: e.g. `"heavy rain, visibility 200m, wind 18 m/s from NE"`.

---

## 3) Training data / positives & negatives

* Positive pairs:

  * same location (within 10km) & time window within ±3 hours with similar event label.
  * different locations having high semantic similarity (pgvector pre-filter or domain rules).
* Negatives:

  * random snapshots far in time or different event type.
* Augmentations:

  * Numeric jitter (Gaussian noise 1–3%)
  * Mask part of text
  * Time shift within ±12h
* Batch size: large (e.g., 512) helps contrastive.
* Optimizer: AdamW, LR schedule (cosine), mix precision.

---

## 4) Evaluation metrics

* k-NN retrieval precision@k for similar weather pairs.
* Clustering quality (Silhouette) for event clusters (Storm/NoStorm).
* Downstream: improved risk ranking AUC/PR on labelled historic floods/storm impacts.

---

## 5) Risk-ranking algorithm (core)

Risk score per WeatherSnapshot = weighted sum of normalized components:

```
Severity = w_p * f_precip(precip_24h, precip_72h) 
         + w_w * f_wind(wind_speed) 
         + w_s * soil_saturation_estimate 
         + w_e * f_elevation(elevation) 
         + w_c * proximity_to_active_event (0/1 or decayed distance)
         + w_v * forecast_prob_extreme (0..1)
```

Where:

* `f_precip` = normalized curve (e.g., log(1 + precip)) capped.
* `f_wind` = piecewise: 0 if <10 m/s, linear to 1 at 50 m/s.
* `soil_saturation_estimate` in [0,1].
* `f_elevation` = lower elevation increases flood risk: `max(0, (h_thresh - elevation)/h_range)` clipped.
* `proximity_to_active_event`: if inside polygon of storm/flood -> 1; else exp(-dist/km / decay_km).
* Weights are tunable; baseline suggestion: `w_p=0.35, w_w=0.25, w_s=0.20, w_e=0.10, w_c=0.10, w_v=0.20` (note these sum >1 because forecast_prob is supplementary — normalize later).

Finally map `Severity` to `Risk Level`:

* 0.0–0.2: Low
* 0.2–0.4: Moderate
* 0.4–0.65: High
* 0.65–1.0: Extreme

Aggregate to Place / Region:

* `PlaceRisk = max(Severity of recent snapshots within radius)` OR `weighted_mean` by distance/time decay or by exposure metric (population/tourist footfall).
* `RegionRisk = max(PlaceRisk)` for conservative; or `percentile(PlaceRisk, 90)`.

---

## 6) Mã Python — toàn bộ pipeline (train + inference + risk scoring)

> **Ghi chú:** code dùng PyTorch, HuggingFace `sentence-transformers`, psycopg2/SQLAlchemy (Postgres). Bạn cần cài: `pip install torch sentence-transformers scikit-learn psycopg2-binary numpy pandas faiss-cpu` (hoặc faiss-gpu), `pgvector` client nếu muốn.

```python
## weather_embedding_pipeline.py
## Full pipeline: preprocessing, dataset, model, training loop (contrastive), inference, saving to Postgres
import os
import math
import random
import json
from typing import List, Dict, Tuple
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

from sentence_transformers import SentenceTransformer

## --------------------------
## Config
## --------------------------
EMB_DIM = 768
TEXT_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
BATCH_SIZE = 256
LR = 2e-5
EPOCHS = 6
TEMPERATURE = 0.07
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

## --------------------------
## Utilities: preprocessing
## --------------------------
NUMERIC_FEATURES = [
    "temperature", "precip_1h", "precip_24h", "precip_72h",
    "humidity", "pressure", "wind_speed", "antecedent_rain_index",
    "distance_to_coast", "elevation", "soil_saturation"
]

def cyclical_encode_month(month_series: pd.Series) -> np.ndarray:
    rad = 2 * math.pi * (month_series - 1) / 12
    return np.vstack((np.sin(rad), np.cos(rad))).T  ## shape (n,2)

def build_weather_text(row: Dict) -> str:
    ## Combine existing description with a short summary
    t = row.get("original_description") or ""
    extra = []
    if row.get("precip_1h") is not None:
        extra.append(f"precip {row['precip_1h']}mm/h")
    if row.get("wind_speed") is not None:
        extra.append(f"wind {row['wind_speed']}m/s")
    if row.get("temperature") is not None:
        extra.append(f"temp {row['temperature']}C")
    return (t + " | " + ", ".join(extra)).strip()

## --------------------------
## Dataset
## --------------------------
class WeatherContrastiveDataset(Dataset):
    """
    Dataset returns:
    - anchor_text, anchor_numeric, pos_text, pos_numeric
    We'll create positive pairs on the fly based on precomputed groups (e.g., same event/location)
    """
    def __init__(self, df: pd.DataFrame, groups_by_key: Dict):
        self.df = df.reset_index(drop=True)
        self.groups = groups_by_key  ## mapping key -> list of indices
        ## Precompute list of indices
        self.indices = list(range(len(self.df)))

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        anchor = self.df.iloc[idx]
        group_key = anchor['group_key']  ## e.g., canonical_event_id or location_timebin
        pos_candidates = self.groups.get(group_key, [])
        if len(pos_candidates) <= 1:
            ## fallback: random near-in-time as positive
            pos_idx = idx
            while pos_idx == idx:
                pos_idx = random.choice(self.indices)
        else:
            pos_idx = random.choice([i for i in pos_candidates if i != idx])

        pos = self.df.iloc[pos_idx]
        return {
            "anchor_text": anchor['weather_text'],
            "anchor_numeric": anchor[NUMERIC_FEATURES].values.astype(np.float32),
            "pos_text": pos['weather_text'],
            "pos_numeric": pos[NUMERIC_FEATURES].values.astype(np.float32),
        }

## --------------------------
## Model
## --------------------------
class WeatherEmbedder(nn.Module):
    def __init__(self, text_model_name=TEXT_MODEL_NAME, emb_dim=EMB_DIM, num_feat_dim=len(NUMERIC_FEATURES)):
        super().__init__()
        ## text encoder (freeze optionally)
        self.text_encoder = SentenceTransformer(text_model_name)
        ## convert sentence-transformers outputs (768) -> 384
        self.text_proj = nn.Sequential(
            nn.Linear(768, 384),
            nn.ReLU(),
            nn.Linear(384, 256),
            nn.ReLU()
        )
        ## numeric encoder
        self.num_mlp = nn.Sequential(
            nn.Linear(num_feat_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
        )
        ## time cyclical or geo can be appended into numeric features if precomputed
        ## fusion + projection
        fusion_dim = 256 + 128
        self.proj = nn.Sequential(
            nn.Linear(fusion_dim, 1024),
            nn.ReLU(),
            nn.Linear(1024, emb_dim)
        )

    def forward_text(self, texts: List[str]) -> torch.Tensor:
        ## sentence-transformers returns numpy array by encode, but it is also wrapped as torch if set
        emb = self.text_encoder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        emb = torch.from_numpy(emb).to(DEVICE).float()
        x = self.text_proj(emb)
        return x

    def forward_numeric(self, num_tensor: torch.Tensor) -> torch.Tensor:
        return self.num_mlp(num_tensor)

    def forward(self, texts: List[str], numerics: torch.Tensor):
        t_emb = self.forward_text(texts)   ## (B, 256)
        n_emb = self.forward_numeric(numerics.to(DEVICE))
        x = torch.cat([t_emb, n_emb], dim=1)
        out = self.proj(x)
        out = F.normalize(out, dim=1)
        return out

## --------------------------
## Contrastive loss (NT-Xent)
## --------------------------
def nt_xent_loss(emb_i, emb_j, temperature=TEMPERATURE):
    ## emb_i, emb_j: (B, D)
    z_i = emb_i
    z_j = emb_j
    batch_size = z_i.shape[0]
    z = torch.cat([z_i, z_j], dim=0)  ## 2B x D
    sim = F.cosine_similarity(z.unsqueeze(1), z.unsqueeze(0), dim=2)  ## 2B x 2B
    sim = sim / temperature
    labels = torch.arange(batch_size).to(DEVICE)
    labels = torch.cat([labels, labels], dim=0)
    mask = torch.eye(2 * batch_size, dtype=torch.bool).to(DEVICE)
    ## For each i, positive is at index i^1 (paired sample)
    positives = torch.cat([torch.diag(sim, batch_size), torch.diag(sim, -batch_size)])
    ## Alternatively use cross-entropy formulation:
    exp_sim = torch.exp(sim) * (~mask)  ## zero out diag
    denom = exp_sim.sum(dim=1)
    ## positive similarity
    pos_sim = torch.exp(torch.cat([F.cosine_similarity(z_i, z_j, dim=1),
                                   F.cosine_similarity(z_j, z_i, dim=1)], dim=0) / temperature)
    loss = -torch.log(pos_sim / denom)
    return loss.mean()

## --------------------------
## Training loop
## --------------------------
def train(model: WeatherEmbedder, train_loader: DataLoader, optimizer, epoch):
    model.train()
    total_loss = 0.0
    for batch_idx, batch in enumerate(train_loader):
        optimizer.zero_grad()
        anchor_texts = batch['anchor_text']
        pos_texts = batch['pos_text']
        anchor_nums = torch.from_numpy(np.stack(batch['anchor_numeric'])).float()
        pos_nums = torch.from_numpy(np.stack(batch['pos_numeric'])).float()
        emb_a = model(anchor_texts, anchor_nums.to(DEVICE))
        emb_p = model(pos_texts, pos_nums.to(DEVICE))
        loss = nt_xent_loss(emb_a, emb_p)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        if batch_idx % 50 == 0:
            print(f"Epoch {epoch} Batch {batch_idx} loss {loss.item():.4f}")
    print("Epoch done, avg loss", total_loss / len(train_loader))

## --------------------------
## Inference save embeddings to Postgres (pgvector)
## --------------------------
def save_embeddings_to_postgres(df: pd.DataFrame, model: WeatherEmbedder, pg_conn_params: Dict, table="weather_embeddings"):
    import psycopg2
    model.eval()
    conn = psycopg2.connect(**pg_conn_params)
    cur = conn.cursor()
    for i in range(0, len(df), 512):
        batch = df.iloc[i:i+512]
        texts = batch["weather_text"].tolist()
        nums = torch.from_numpy(np.vstack(batch[NUMERIC_FEATURES].values)).float()
        with torch.no_grad():
            emb = model(texts, nums.to(DEVICE)).cpu().numpy()
        ## upsert into table: id, embedding
        for idx, row_emb in zip(batch['id'].tolist(), emb):
            ## convert to pgvector string
            vec_str = ",".join([str(float(x)) for x in row_emb])
            cur.execute(f"""
                INSERT INTO {table} (weather_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (weather_id) DO UPDATE SET embedding = EXCLUDED.embedding
            """, (int(idx), vec_str))
        conn.commit()
    cur.close()
    conn.close()

## --------------------------
## Risk scoring function (single snapshot)
## --------------------------
def normalize(x, minv, maxv):
    if x is None:
        return 0.0
    if maxv == minv:
        return 0.0
    return float((x - minv) / (maxv - minv))

def compute_severity(snapshot: Dict, params: Dict = None) -> float:
    ## params: thresholds and weights
    if params is None:
        params = {
            "w_p": 0.35,
            "w_w": 0.25,
            "w_s": 0.20,
            "w_e": 0.10,
            "w_c": 0.10,
            "w_v": 0.20,
            "precip_24h_max": 200.0,   ## mm
            "wind_max": 60.0,          ## m/s
            "elev_thresh": 50.0,       ## meters
            "decay_km": 50.0
        }
    precip = snapshot.get('precip_24h', 0.0)
    wind = snapshot.get('wind_speed', 0.0)
    soil = snapshot.get('soil_saturation', 0.0)
    elevation = snapshot.get('elevation', 0.0)
    proximity_km = snapshot.get('proximity_to_active_event_km', 9999.0)
    forecast_prob = snapshot.get('forecast_prob_extreme', 0.0)

    f_precip = math.log1p(precip) / math.log1p(params['precip_24h_max'])
    f_precip = min(1.0, f_precip)
    f_wind = min(1.0, wind / params['wind_max'])
    f_elev = max(0.0, (params['elev_thresh'] - elevation) / params['elev_thresh'])
    f_prox = 1.0 if proximity_km <= 0 else math.exp(-proximity_km / params['decay_km'])

    score = (params['w_p'] * f_precip +
             params['w_w'] * f_wind +
             params['w_s'] * soil +
             params['w_e'] * f_elev +
             params['w_c'] * f_prox +
             params['w_v'] * forecast_prob)
    ## normalize: clamp 0..1
    score = max(0.0, min(1.0, score))
    return score

## --------------------------
## Aggregate to Place / Region
## --------------------------
def aggregate_place_risk(place_snapshot_list: List[Dict], method="max", time_decay_hours=48):
    ## place_snapshot_list: list of snapshots dicts with 'score' and 'timestamp'
    if method == "max":
        return max([s['score'] for s in place_snapshot_list]) if place_snapshot_list else 0.0
    elif method == "time_decay_avg":
        now_ts = max([s['timestamp'] for s in place_snapshot_list])
        weights = []
        for s in place_snapshot_list:
            hours = (now_ts - s['timestamp']).total_seconds() / 3600.0
            w = math.exp(-hours / time_decay_hours)
            weights.append(w)
        numerator = sum([s['score'] * w for s, w in zip(place_snapshot_list, weights)])
        denom = sum(weights) if weights else 1.0
        return numerator / denom
    else:
        raise ValueError("unknown method")

## --------------------------
## Main (example)
## --------------------------
def example_run():
    ## load CSV or read from Postgres
    df = pd.read_csv("weather_data_preprocessed.csv")
    ## build groups: use location bin or event_id
    groups = {}
    for idx, row in df.iterrows():
        k = row.get('event_id') or f"locbin_{int(row['latitude']*10)}_{int(row['longitude']*10)}"
        df.at[idx, 'group_key'] = k
        groups.setdefault(k, []).append(idx)
    ## fit scaler on numeric features
    scaler = StandardScaler()
    df[NUMERIC_FEATURES] = scaler.fit_transform(df[NUMERIC_FEATURES].fillna(0.0))
    ## build weather_text
    df['weather_text'] = df.apply(build_weather_text, axis=1)

    ## split
    train_df, val_df = train_test_split(df, test_size=0.02, random_state=42)

    train_ds = WeatherContrastiveDataset(train_df, groups)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=lambda x: x)

    model = WeatherEmbedder().to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    for epoch in range(1, EPOCHS+1):
        train(model, train_loader, optimizer, epoch)
        ## optionally run validation, save model
        torch.save(model.state_dict(), f"weather_embedder_epoch{epoch}.pt")

    ## inference save to Postgres (assume table weather_embeddings exists)
    pg_conn = {"host":"localhost","port":5432,"user":"user","password":"pw","dbname":"kg"}
    save_embeddings_to_postgres(df, model, pg_conn, table="weather_embeddings")

if __name__ == "__main__":
    example_run()
```

> Lưu ý: đoạn code trên là template — bạn sẽ cần điều chỉnh `groups` logic (positive mining), bổ sung batching hiệu quả cho text encoder (sentence-transformers), và có thể freeze text encoder để tiết kiệm GPU.

---

## 7) Mã Python: risk-ranking standalone (sẵn dùng)

```python
## risk_scoring.py
import math
from datetime import datetime
from typing import Dict, List

DEFAULT_PARAMS = {
    "w_p": 0.35,
    "w_w": 0.25,
    "w_s": 0.20,
    "w_e": 0.10,
    "w_c": 0.10,
    "w_v": 0.20,
    "precip_24h_max": 200.0,
    "wind_max": 60.0,
    "elev_thresh": 50.0,
    "decay_km": 50.0
}

def compute_severity(snapshot: Dict, params: Dict = None) -> float:
    if params is None:
        params = DEFAULT_PARAMS
    precip = snapshot.get('precip_24h', 0.0) or 0.0
    wind = snapshot.get('wind_speed', 0.0) or 0.0
    soil = min(max(snapshot.get('soil_saturation', 0.0) or 0.0, 0.0), 1.0)
    elevation = snapshot.get('elevation', 0.0) or 0.0
    proximity_km = snapshot.get('proximity_to_active_event_km', 9999.0)
    forecast_prob = min(max(snapshot.get('forecast_prob_extreme', 0.0) or 0.0, 0.0), 1.0)

    f_precip = math.log1p(precip) / math.log1p(params['precip_24h_max'])
    f_precip = min(1.0, max(0.0, f_precip))
    f_wind = min(1.0, max(0.0, wind / params['wind_max']))
    f_elev = max(0.0, (params['elev_thresh'] - elevation) / params['elev_thresh'])
    f_prox = 1.0 if proximity_km <= 0 else math.exp(-proximity_km / params['decay_km'])

    score = (params['w_p'] * f_precip +
             params['w_w'] * f_wind +
             params['w_s'] * soil +
             params['w_e'] * f_elev +
             params['w_c'] * f_prox +
             params['w_v'] * forecast_prob)
    score = max(0.0, min(1.0, score))
    return score

def risk_level(score: float) -> str:
    if score < 0.2:
        return "low"
    elif score < 0.4:
        return "moderate"
    elif score < 0.65:
        return "high"
    else:
        return "extreme"

## aggregate at place
def aggregate_place(snapshot_list: List[Dict], method="max"):
    if not snapshot_list:
        return {"score": 0.0, "level": "low"}
    if method == "max":
        best = max(snapshot_list, key=lambda s: s['score'])
        return {"score": best['score'], "level": risk_level(best['score'])}
    elif method == "time_decay_avg":
        ## assume snapshot timestamp are datetime
        now = max([s['timestamp'] for s in snapshot_list])
        numerator = 0.0
        denom = 0.0
        for s in snapshot_list:
            hours = (now - s['timestamp']).total_seconds() / 3600.0
            w = math.exp(-hours / 48.0)
            numerator += s['score'] * w
            denom += w
        avg = numerator / denom if denom > 0 else 0.0
        return {"score": avg, "level": risk_level(avg)}
    else:
        raise ValueError("Unknown")

## Example usage
if __name__ == "__main__":
    sample = {
        "precip_24h": 120.0,
        "wind_speed": 18.0,
        "soil_saturation": 0.8,
        "elevation": 10,
        "proximity_to_active_event_km": 5,
        "forecast_prob_extreme": 0.7
    }
    s = compute_severity(sample)
    print("score", s, "level", risk_level(s))
```

---

## 8) Lưu embedding vào Postgres (pgvector) — schema gợi ý

SQL để tạo bảng lưu embedding:

```sql
CREATE TABLE IF NOT EXISTS weather_embeddings (
  weather_id BIGINT PRIMARY KEY,
  embedding vector(768),
  model_version TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- create ivfflat or hnsw depending on pgvector version
CREATE INDEX IF NOT EXISTS idx_weather_embeddings_ivf ON weather_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- Or HNSW:
-- CREATE INDEX IF NOT EXISTS idx_weather_embeddings_hnsw ON weather_embeddings USING hnsw (embedding);
```

Lưu ý: pgvector has specific ops; chọn `ivfflat`/`hnsw` according to version and memory.

---

## 9) Ops, Backfill & Model Versioning

* Store `model_version` with embeddings. When re-train, run backfill job (Airflow) to re-embed historical snapshots; keep old embeddings for A/B test.
* Use incremental re-embed for new data.
* Maintain a retraining cadence: weekly for seasonal trends, monthly for major model updates.

---

## 10) Tuning & Practical tips (Vietnam-specific)

* Pretrain text encoder with Vietnamese weather text augmentation (translate common METAR/TAF phrases into VN idioms) to improve semantic mapping.
* Use local climate patterns: monsoon, typhoon season (Jun–Nov) — add boolean features `is_typhoon_season`.
* Soil saturation estimation: can be improved by integrating ERA5 or local hydrological datasets — but a simple antecedent rainfall works for bootstrap.
* For coastal flood risk: incorporate tide forecast & surge model if available.

---

## 11) Evaluation & production validation

* Validate risk scoring using historical disaster reports (flood extents, recorded damage) — compute ROC/AUC of score predicting impact events.
* Embedding: evaluate retrieval — e.g., for each labeled storm snapshot, retrieve top-10 neighbors and compute recall@k.
* Monitor distribution drift: if embedding norm or feature distribution shifts, alert and retrain.

---

## 12) Next steps I can do for you (pick 1 or more)

* Viết script ETL cụ thể để lấy `precip_72h` / antecedent rainfall từ time-series trong Postgres.
* Tối ưu `groups` mining cho contrastive (nearby-in-time positive mining).
* Baked demo: train a small model on synthetic data I generate to show end-to-end.
* Tinh chỉnh weights cho risk scoring bằng historical event labels (learn weights via logistic regression on labeled impacts).

