"""
Per-chart-type reference examples injected into the code generation prompt.

Data layout that chart code should use:
  single series:   data["labels"], data["values"]
  grouped/stacked: data["categories"], data["SeriesName1"], data["SeriesName2"]
  scatter:         data["x"], data["y"]  |  data["SeriesA_x"], data["SeriesA_y"]
  histogram:       data["values"]  or  data["GroupName"]
  box plot:        data["GroupName1"], data["GroupName2"]
  heatmap:         data["rows"], data["cols"], data["matrix"]
  metadata:        data["title"], data["x_label"], data["y_label"]  (may be "")
"""

BAR = """\
=== REFERENCE EXAMPLES: bar chart ===

```python
# --- basic bar, single series ---
fig, ax = plt.subplots(figsize=(9, 5))
labels = data["labels"]
values = data["values"]
bars = ax.bar(labels, values, color="steelblue", edgecolor="white", linewidth=0.8)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
ax.grid(axis="y", linestyle="--", alpha=0.5)
if any(len(str(l)) > 6 for l in labels): ax.tick_params(axis="x", rotation=45)
fig.tight_layout()

# --- value labels on top of bars ---
for b in bars:
    ax.text(b.get_x() + b.get_width()/2, b.get_height() + max(values)*0.01,
            f"{b.get_height():,.1f}", ha="center", va="bottom", fontsize=9)

# --- grouped bars (multi-series: data["categories"], data["SeriesA"], data["SeriesB"]) ---
fig, ax = plt.subplots(figsize=(10, 5))
categories = data["categories"]
series_keys = [k for k in data if k not in ("categories", "title", "x_label", "y_label", "chart_type")]
x = np.arange(len(categories))
w = 0.8 / len(series_keys)
for i, key in enumerate(series_keys):
    offset = (i - len(series_keys)/2 + 0.5) * w
    ax.bar(x + offset, data[key], w, label=key)
ax.set_xticks(x); ax.set_xticklabels(categories)
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- color by sign (diverging: green positive, red negative) ---
colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in data["values"]]
fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(data["labels"], data["values"], color=colors, edgecolor="white")
ax.axhline(0, color="black", linewidth=0.8)
ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- color by quartile ---
values = data["values"]
q1, q2, q3 = np.percentile(values, [25, 50, 75])
qcolors = ["#aed6f1" if v <= q1 else "#3498db" if v <= q2 else "#1a5276" if v <= q3 else "#0a2342"
           for v in values]
fig, ax = plt.subplots(figsize=(9, 5))
ax.bar(data["labels"], values, color=qcolors, edgecolor="white")
ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- horizontal sorted bars ---
values = data["values"]; labels = data["labels"]
order = np.argsort(values)[::-1]
fig, ax = plt.subplots(figsize=(8, max(4, len(labels)*0.4)))
ax.barh([labels[i] for i in order], [values[i] for i in order], color="steelblue")
ax.grid(axis="x", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

LINE = """\
=== REFERENCE EXAMPLES: line chart ===

```python
# --- basic single line ---
fig, ax = plt.subplots(figsize=(10, 5))
labels = data["labels"]; values = data["values"]
ax.plot(labels, values, color="steelblue", linewidth=2, marker="o", markersize=4)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
ax.grid(linestyle="--", alpha=0.5)
if any(len(str(l)) > 6 for l in labels): ax.tick_params(axis="x", rotation=45)
fig.tight_layout()

# --- multi-series lines (data["categories"] + named series keys) ---
fig, ax = plt.subplots(figsize=(10, 5))
x_vals = data["categories"]
series_keys = [k for k in data if k not in ("categories", "title", "x_label", "y_label", "chart_type")]
colors = plt.cm.tab10.colors
for idx, key in enumerate(series_keys):
    ax.plot(x_vals, data[key], linewidth=2, marker="o", markersize=4,
            color=colors[idx % len(colors)], label=key)
ax.legend(); ax.grid(linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- rolling mean overlay ---
values = data["values"]; labels = data["labels"]; window = 5
sma = [np.mean(values[max(0,i-window+1):i+1]) if i >= window-1 else np.nan
       for i in range(len(values))]
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(labels, values, color="lightgrey", linewidth=1.5, label="Raw")
ax.plot(labels, sma, color="steelblue", linewidth=2.5, label=f"MA({window})")
ax.legend(); ax.grid(linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- segment coloring (green up, red down) ---
x_vals = data["labels"]; y_vals = data["values"]
fig, ax = plt.subplots(figsize=(10, 5))
for i in range(len(x_vals)-1):
    color = "#2ecc71" if y_vals[i+1] >= y_vals[i] else "#e74c3c"
    ax.plot([x_vals[i], x_vals[i+1]], [y_vals[i], y_vals[i+1]], color=color, linewidth=2.5)
ax.grid(linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

STACKED_BAR = """\
=== REFERENCE EXAMPLES: stacked bar chart ===

```python
# --- basic stacked bar ---
fig, ax = plt.subplots(figsize=(10, 5))
categories = data["categories"]
series_keys = [k for k in data if k not in ("categories", "title", "x_label", "y_label", "chart_type")]
bottom = np.zeros(len(categories))
colors = plt.cm.tab10.colors
for idx, key in enumerate(series_keys):
    vals = np.array(data[key], dtype=float)
    ax.bar(categories, vals, bottom=bottom, label=key,
           color=colors[idx % len(colors)], edgecolor="white", linewidth=0.5)
    bottom += vals
ax.legend(loc="upper right"); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
if any(len(str(c)) > 6 for c in categories): ax.tick_params(axis="x", rotation=45)
fig.tight_layout()

# --- with total annotations on top ---
categories = data["categories"]
series_keys = [k for k in data if k not in ("categories", "title", "x_label", "y_label", "chart_type")]
bottom = np.zeros(len(categories)); totals = np.zeros(len(categories))
colors = plt.cm.tab10.colors
fig, ax = plt.subplots(figsize=(10, 5))
for idx, key in enumerate(series_keys):
    vals = np.array(data[key], dtype=float)
    ax.bar(categories, vals, bottom=bottom, label=key,
           color=colors[idx % len(colors)], edgecolor="white")
    bottom += vals; totals += vals
for i, total in enumerate(totals):
    ax.text(i, total + max(totals)*0.01, f"{total:,.0f}",
            ha="center", va="bottom", fontsize=9, fontweight="bold")
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

PIE = """\
=== REFERENCE EXAMPLES: pie chart ===

```python
# --- basic pie ---
fig, ax = plt.subplots(figsize=(8, 7))
labels = data["labels"]; values = data["values"]
wedges, texts, autotexts = ax.pie(
    values, labels=labels, autopct="%1.1f%%", startangle=90,
    wedgeprops={"edgecolor": "white", "linewidth": 1.5},
)
for at in autotexts: at.set_fontsize(9)
if data.get("title"): ax.set_title(data["title"], fontsize=14, pad=16)
ax.axis("equal"); fig.tight_layout()

# --- merge small slices (<5%) into "Other" ---
labels = data["labels"]; values = data["values"]
total = sum(values); threshold = 0.05 * total
ml, mv, other = [], [], 0
for l, v in zip(labels, values):
    if v >= threshold: ml.append(l); mv.append(v)
    else: other += v
if other > 0: ml.append("Other"); mv.append(other)
fig, ax = plt.subplots(figsize=(8, 7))
ax.pie(mv, labels=ml, autopct="%1.1f%%", startangle=90,
       wedgeprops={"edgecolor": "white", "linewidth": 1.5})
ax.axis("equal")
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- explode dominant slice ---
values = data["values"]; max_idx = int(np.argmax(values))
explode = [0.08 if i == max_idx else 0 for i in range(len(values))]
fig, ax = plt.subplots(figsize=(8, 7))
ax.pie(values, labels=data["labels"], autopct="%1.1f%%", explode=explode, startangle=90,
       wedgeprops={"edgecolor": "white"})
ax.axis("equal")
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

DOUGHNUT = """\
=== REFERENCE EXAMPLES: doughnut chart ===

```python
# --- basic doughnut (width=0.5 creates the hole) ---
fig, ax = plt.subplots(figsize=(8, 7))
labels = data["labels"]; values = data["values"]
wedges, texts, autotexts = ax.pie(
    values, labels=labels, autopct="%1.1f%%", startangle=90,
    wedgeprops={"width": 0.5, "edgecolor": "white", "linewidth": 1.5},
)
for at in autotexts: at.set_fontsize(9)
total = sum(values)
ax.text(0, 0, f"Total\n{total:,.0f}", ha="center", va="center", fontsize=12, fontweight="bold")
if data.get("title"): ax.set_title(data["title"], fontsize=14, pad=16)
ax.axis("equal"); fig.tight_layout()

# --- performance coloring (green >=90%, yellow 70-89%, red <70%) ---
labels = data["labels"]; values = data["values"]
total = sum(values); pcts = [v/total*100 for v in values]
colors = ["#2ecc71" if p >= 90 else "#f39c12" if p >= 70 else "#e74c3c" for p in pcts]
fig, ax = plt.subplots(figsize=(8, 7))
ax.pie(values, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90,
       wedgeprops={"width": 0.5, "edgecolor": "white"})
ax.axis("equal")
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

SCATTER = """\
=== REFERENCE EXAMPLES: scatter chart ===

```python
# --- basic scatter ---
fig, ax = plt.subplots(figsize=(8, 6))
ax.scatter(data["x"], data["y"], alpha=0.7, s=60, color="steelblue",
           edgecolors="white", linewidths=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
ax.grid(linestyle="--", alpha=0.5); fig.tight_layout()

# --- regression line + R^2 ---
xs = np.array(data["x"], dtype=float); ys = np.array(data["y"], dtype=float)
coeffs = np.polyfit(xs, ys, 1)
trend_x = np.linspace(xs.min(), xs.max(), 200)
corr = np.corrcoef(xs, ys)[0, 1]
fig, ax = plt.subplots(figsize=(8, 6))
ax.scatter(xs, ys, alpha=0.7, s=60, color="steelblue", edgecolors="white")
ax.plot(trend_x, np.polyval(coeffs, trend_x), "r--", linewidth=1.8, label=f"R2={corr**2:.3f}")
ax.legend(); ax.grid(linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- multi-series scatter (data["SeriesA_x"], data["SeriesA_y"], ...) ---
fig, ax = plt.subplots(figsize=(8, 6))
meta_keys = {"title", "x_label", "y_label", "chart_type"}
series_names = list(dict.fromkeys(
    k.rsplit("_", 1)[0] for k in data
    if k not in meta_keys and (k.endswith("_x") or k.endswith("_y"))
))
colors = plt.cm.tab10.colors
for idx, name in enumerate(series_names):
    ax.scatter(data[f"{name}_x"], data[f"{name}_y"], label=name,
               alpha=0.7, s=60, color=colors[idx % len(colors)], edgecolors="white")
ax.legend(); ax.grid(linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

AREA = """\
=== REFERENCE EXAMPLES: area chart ===

```python
# --- basic single area ---
fig, ax = plt.subplots(figsize=(10, 5))
x_vals = range(len(data["labels"]))
ax.fill_between(x_vals, data["values"], alpha=0.35, color="steelblue")
ax.plot(x_vals, data["values"], color="steelblue", linewidth=2)
ax.set_xticks(list(x_vals)); ax.set_xticklabels(data["labels"])
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
ax.grid(linestyle="--", alpha=0.4)
if any(len(str(l)) > 6 for l in data["labels"]): ax.tick_params(axis="x", rotation=45)
fig.tight_layout()

# --- stacked area (multi-series) ---
fig, ax = plt.subplots(figsize=(10, 5))
categories = data["categories"]
series_keys = [k for k in data if k not in ("categories", "title", "x_label", "y_label", "chart_type")]
x_vals = range(len(categories))
ys_list = [data[k] for k in series_keys]
colors = plt.cm.tab10.colors[:len(series_keys)]
ax.stackplot(x_vals, *ys_list, labels=series_keys, alpha=0.8, colors=colors)
ax.set_xticks(list(x_vals)); ax.set_xticklabels(categories)
ax.legend(loc="upper left"); ax.grid(linestyle="--", alpha=0.4)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- threshold-split area ---
values = np.array(data["values"]); labels = data["labels"]
threshold = float(np.mean(values))
x_vals = np.arange(len(values))
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(x_vals, values, color="black", linewidth=1.5)
ax.fill_between(x_vals, values, threshold,
                where=(values >= threshold), alpha=0.4, color="#2ecc71", label="Above avg")
ax.fill_between(x_vals, values, threshold,
                where=(values < threshold), alpha=0.4, color="#e74c3c", label="Below avg")
ax.axhline(threshold, color="grey", linestyle="--", linewidth=1)
ax.set_xticks(list(x_vals)); ax.set_xticklabels(labels)
ax.legend(); ax.grid(linestyle="--", alpha=0.4)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

HISTOGRAM = """\
=== REFERENCE EXAMPLES: histogram ===

```python
# --- ALWAYS use ax.hist(), NOT ax.bar() for histograms ---
fig, ax = plt.subplots(figsize=(9, 5))
values = data["values"]
n, bins, patches = ax.hist(values, bins=20, color="steelblue", alpha=0.8, edgecolor="white")
mean_v, std_v = np.mean(values), np.std(values)
ax.axvline(mean_v, color="red", linestyle="--", linewidth=1.8, label=f"Mean={mean_v:.1f}")
ax.axvline(mean_v + std_v, color="orange", linestyle=":", linewidth=1.2)
ax.axvline(mean_v - std_v, color="orange", linestyle=":", linewidth=1.2)
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "Value")); ax.set_ylabel(data.get("y_label", "Frequency"))
fig.tight_layout()

# --- multi-group overlapping histograms (data["GroupA"], data["GroupB"]) ---
fig, ax = plt.subplots(figsize=(9, 5))
meta_keys = {"title", "x_label", "y_label", "chart_type"}
group_keys = [k for k in data if k not in meta_keys]
colors = plt.cm.tab10.colors
for idx, key in enumerate(group_keys):
    ax.hist(data[key], bins=20, alpha=0.55, color=colors[idx % len(colors)],
            edgecolor="white", label=key)
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()

# --- mean +- 2 sigma shading ---
values = data["values"]
mean_v, std_v = np.mean(values), np.std(values)
fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(values, bins=20, color="lightsteelblue", edgecolor="white", zorder=2)
ax.axvspan(mean_v - std_v, mean_v + std_v, alpha=0.25, color="steelblue", label="+-1sigma")
ax.axvspan(mean_v - 2*std_v, mean_v + 2*std_v, alpha=0.12, color="steelblue", label="+-2sigma")
ax.axvline(mean_v, color="red", linestyle="--", linewidth=1.8, label="Mean")
ax.legend(); ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

BOX = """\
=== REFERENCE EXAMPLES: box plot ===

```python
# --- ALWAYS pass data as list of arrays, use patch_artist=True for colors ---
fig, ax = plt.subplots(figsize=(9, 5))
meta_keys = {"title", "x_label", "y_label", "chart_type"}
group_keys = [k for k in data if k not in meta_keys]
bp = ax.boxplot([data[k] for k in group_keys], tick_labels=group_keys,
                patch_artist=True, showmeans=True, showfliers=True,
                meanprops={"marker": "D", "markerfacecolor": "red", "markersize": 6})
colors = plt.cm.Pastel1.colors
for patch, color in zip(bp["boxes"], colors):
    patch.set_facecolor(color)
ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
ax.set_xlabel(data.get("x_label", "")); ax.set_ylabel(data.get("y_label", ""))
if any(len(k) > 6 for k in group_keys): ax.tick_params(axis="x", rotation=45)
fig.tight_layout()

# --- sorted by median ---
meta_keys = {"title", "x_label", "y_label", "chart_type"}
group_keys = [k for k in data if k not in meta_keys]
sorted_keys = sorted(group_keys, key=lambda k: float(np.median(data[k])), reverse=True)
fig, ax = plt.subplots(figsize=(9, 5))
ax.boxplot([data[k] for k in sorted_keys], tick_labels=sorted_keys,
           patch_artist=True, showfliers=True)
ax.grid(axis="y", linestyle="--", alpha=0.5)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

HEATMAP = """\
=== REFERENCE EXAMPLES: heatmap ===

```python
# --- basic heatmap with cell annotations ---
fig, ax = plt.subplots(figsize=(max(8, len(data["cols"])), max(5, len(data["rows"])*0.6)))
matrix = np.array(data["matrix"], dtype=float)
im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", interpolation="nearest")
ax.set_xticks(range(len(data["cols"]))); ax.set_xticklabels(data["cols"], rotation=45, ha="right")
ax.set_yticks(range(len(data["rows"]))); ax.set_yticklabels(data["rows"])
vmax = np.nanmax(matrix)
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if not np.isnan(val):
            color = "white" if val > vmax * 0.65 else "black"
            ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8, color=color)
fig.colorbar(im, ax=ax, shrink=0.8)
if data.get("title"): ax.set_title(data["title"], fontsize=14, pad=12)
fig.tight_layout()

# --- diverging colormap (symmetric blue-white-red) ---
matrix = np.array(data["matrix"], dtype=float)
vabs = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)))
fig, ax = plt.subplots(figsize=(max(8, len(data["cols"])), max(5, len(data["rows"])*0.6)))
im = ax.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-vabs, vmax=vabs)
ax.set_xticks(range(len(data["cols"]))); ax.set_xticklabels(data["cols"], rotation=45, ha="right")
ax.set_yticks(range(len(data["rows"]))); ax.set_yticklabels(data["rows"])
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if not np.isnan(val):
            ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8)
fig.colorbar(im, ax=ax, shrink=0.8)
if data.get("title"): ax.set_title(data["title"], fontsize=14)
fig.tight_layout()
```
"""

TEMPLATES: dict[str, str] = {
    "bar": BAR,
    "line": LINE,
    "stacked_bar": STACKED_BAR,
    "pie": PIE,
    "doughnut": DOUGHNUT,
    "scatter": SCATTER,
    "area": AREA,
    "histogram": HISTOGRAM,
    "box": BOX,
    "box_plot": BOX,
    "heatmap": HEATMAP,
}


def get_template(chart_type: str) -> str:
    return TEMPLATES.get((chart_type or "bar").lower(), BAR)
