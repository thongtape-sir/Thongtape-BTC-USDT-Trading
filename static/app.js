const state = {
  liveTradingEnabled: false,
  baseAsset: "BTC",
  quoteAsset: "USDT",
  chartInterval: "1m",
  candles: [],
  chartViewCount: 160,
  levels: {
    support: null,
    resistance: null,
    current: null,
  },
};

const $ = (id) => document.getElementById(id);

const formatUsd = (value, maximumFractionDigits = 2) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits,
  }).format(Number(value));
};

const formatNumber = (value, maximumFractionDigits = 6) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(Number(value));
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload;
}

function setStatus(message, className = "neutral") {
  $("connectionStatus").className = `pill ${className}`;
  $("connectionStatus").textContent = message;
}

async function loadHealth() {
  const health = await api("/api/health");
  state.liveTradingEnabled = health.liveTradingEnabled;
  state.baseAsset = health.baseAsset || "BTC";
  state.quoteAsset = health.quoteAsset || "USDT";

  if (health.manualLiveTradingEnabled) {
    $("tradingStatus").textContent = "Manual live on";
    $("tradingStatus").className = "pill danger";
  } else if (health.aiLiveOrdersEnabled) {
    $("tradingStatus").textContent = "Manual off · AI live on";
    $("tradingStatus").className = "pill warning";
  } else {
    $("tradingStatus").textContent = "Live trading off";
    $("tradingStatus").className = "pill warning";
  }
}

async function loadMarket() {
  try {
    const market = await api("/api/market");
    $("ethPrice").textContent = formatUsd(market.price, 2);
    $("highPrice").textContent = formatUsd(market.highPrice, 2);
    $("lowPrice").textContent = formatUsd(market.lowPrice, 2);
    $("volume").textContent = formatNumber(market.volume, 2);
    const change = Number(market.priceChangePercent);
    $("priceChange").textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}% 24h`;
    $("priceChange").className = change >= 0 ? "ok-text" : "danger-text";
    renderSignal(market.signal);
    setStatus("Connected", "ok");
  } catch (error) {
    setStatus(error.message, "danger");
  }
}

async function loadAccount() {
  $("accountMessage").textContent = "Loading portfolio...";
  try {
    const account = await api("/api/account");
    const base = account.base || account.eth || {};
    $("ethQty").textContent = formatNumber(base.quantity, 8);
    $("ethValue").textContent = formatUsd(base.valueUsdt);
    $("usdtQty").textContent = formatNumber(account.usdt?.quantity, 2);
    $("portfolioValue").textContent = formatUsd(account.portfolio?.trackedValueUsdt);
    $("realizedPnl").textContent = formatUsd(account.pnl?.realizedUsdt);
    $("unrealizedPnl").textContent = formatUsd(account.pnl?.unrealizedUsdt);
    $("totalPnl").textContent = formatUsd(account.pnl?.totalUsdt);
    $("pnlWarning").textContent = account.pnl?.warning || "";
    $("accountMessage").textContent = account.portfolio?.note || "";
  } catch (error) {
    $("accountMessage").textContent = error.message;
  }
}

async function loadOrderHistory() {
  try {
    const payload = await api("/api/orders/history");
    renderOrderHistory(payload);
  } catch (error) {
    $("historyRows").innerHTML = `<tr><td colspan="7">${error.message}</td></tr>`;
  }
}

function renderOrderHistory(payload) {
  const summary = payload.summary || {};
  const orders = payload.orders || [];
  $("historyLiveCount").textContent = summary.liveOrderCount ?? "--";
  $("historyDryRunCount").textContent = summary.dryRunCount ?? "--";
  $("historyNetEth").textContent = formatNumber(summary.netQtyBase ?? summary.netQtyEth, 8);
  $("historyTotalPnl").textContent = formatUsd(summary.estimatedTotalUsdt, 2);
  $("historyNote").textContent = summary.note || "";

  $("historyRows").innerHTML = "";
  if (!orders.length) {
    $("historyRows").innerHTML = '<tr><td colspan="7">No order history yet</td></tr>';
    return;
  }

  orders.slice(0, 80).forEach((order) => {
    const row = document.createElement("tr");
    const orderBaseAsset = baseAssetFromSymbol(order.symbol) || state.baseAsset;
    const amount = order.quoteOrderQty
      ? `${formatNumber(order.quoteOrderQty, 2)} ${state.quoteAsset}`
      : `${formatNumber(order.quantity, 8)} ${orderBaseAsset}`;
    const executed = order.executedQty
      ? `${formatNumber(order.executedQty, 8)} ${orderBaseAsset} / ${formatUsd(order.cummulativeQuoteQty, 2)}`
      : "--";
    row.innerHTML = `
      <td>${formatHistoryTime(order.createdAt)}</td>
      <td>${order.source || "--"}</td>
      <td>${order.status || "--"}</td>
      <td>${order.side || "--"}</td>
      <td>${amount}</td>
      <td>${executed}</td>
      <td>${order.reason || "--"}</td>
    `;
    $("historyRows").appendChild(row);
  });
}

function baseAssetFromSymbol(symbol) {
  if (!symbol || !symbol.endsWith("USDT")) return null;
  return symbol.slice(0, -4);
}

function formatHistoryTime(value) {
  if (!value) return "--";
  return new Intl.DateTimeFormat("th-TH", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function renderSignal(signal) {
  const plan = signal.tradePlan || {};
  const indicators = signal.indicators || {};
  $("signalAction").textContent = signal.decision ? `${signal.decision} · ${signal.action}` : signal.action || "--";
  $("signalConfidence").textContent = signal.confidence ? `${Math.round(signal.confidence * 100)}%` : "--";
  $("signalSummary").textContent = signal.summary || "--";
  $("entryZone").textContent = `${formatUsd(plan.entryLow, 2)} - ${formatUsd(plan.entryHigh, 2)}`;
  $("stopLoss").textContent = formatUsd(plan.stopLoss, 2);
  $("takeProfit1").textContent = formatUsd(plan.takeProfit1, 2);
  $("takeProfit2").textContent = formatUsd(plan.takeProfit2, 2);
  $("supportLevel").textContent = formatUsd(plan.support, 2);
  $("resistanceLevel").textContent = formatUsd(plan.resistance, 2);
  $("currentPriceLevel").textContent = formatUsd(plan.currentPrice, 2);
  state.levels = {
    support: Number.isFinite(Number(plan.support)) ? Number(plan.support) : null,
    resistance: Number.isFinite(Number(plan.resistance)) ? Number(plan.resistance) : null,
    current: Number.isFinite(Number(plan.currentPrice)) ? Number(plan.currentPrice) : null,
  };
  $("riskReward").textContent = plan.riskRewardToTp1
    ? `Risk/Reward to TP1 ~ ${plan.riskRewardToTp1}:1 · Support ${formatUsd(plan.support, 2)} · Resistance ${formatUsd(plan.resistance, 2)}`
    : "";

  $("signalReasons").innerHTML = "";
  (signal.reasons || []).forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    $("signalReasons").appendChild(item);
  });

  $("rsiValue").textContent = `RSI ${indicators.rsi14 ?? "--"}`;
  $("ma7Value").textContent = `MA7 ${formatUsd(indicators.ma7, 2)}`;
  $("ma30Value").textContent = `MA30 ${formatUsd(indicators.ma30, 2)}`;
  $("ma99Value").textContent = `MA99 ${formatUsd(indicators.ma99, 2)}`;
  $("atrValue").textContent = `ATR ${formatUsd(indicators.atr14, 2)}`;
  drawCandles();
}

async function loadBotConfig() {
  try {
    const config = await api("/api/bot/config");
    renderBotConfig(config);
  } catch (error) {
    $("botRulesMessage").textContent = error.message;
  }
}

function renderBotConfig(config) {
  $("botEnabled").checked = Boolean(config.enabled);
  $("botDryRunOnly").checked = Boolean(config.dryRunOnly);
  $("botAllowBuy").checked = Boolean(config.allowBuy);
  $("botAllowSell").checked = Boolean(config.allowSell);
  $("botMinConfidence").value = Math.round(Number(config.minConfidence || 0) * 100);
  $("botBuyBuffer").value = config.buyBelowResistancePct ?? 0.35;
  $("botSellBuffer").value = config.sellAboveSupportPct ?? 0.35;
  $("botOrderUsdt").value = config.orderUsdt ?? 10;
  $("botSellQtyBtc").value = config.sellQtyBtc ?? 0.0001;
  $("botDailyBudget").value = config.dailyBudgetUsdt ?? 25;
  updateBotMode();
  $("botRulesMessage").textContent = "Rules loaded. .env safety limits still apply.";
}

function collectBotConfig() {
  return {
    enabled: $("botEnabled").checked,
    dryRunOnly: $("botDryRunOnly").checked,
    allowBuy: $("botAllowBuy").checked,
    allowSell: $("botAllowSell").checked,
    minConfidence: Number($("botMinConfidence").value) / 100,
    buyBelowResistancePct: Number($("botBuyBuffer").value),
    sellAboveSupportPct: Number($("botSellBuffer").value),
    orderUsdt: Number($("botOrderUsdt").value),
    sellQtyBtc: Number($("botSellQtyBtc").value),
    dailyBudgetUsdt: Number($("botDailyBudget").value),
  };
}

async function saveBotConfig() {
  $("botRulesMessage").textContent = "Saving rules...";
  try {
    const saved = await api("/api/bot/config", {
      method: "PUT",
      body: JSON.stringify(collectBotConfig()),
    });
    renderBotConfig(saved);
    $("botRulesMessage").textContent = "Bot Rules saved.";
  } catch (error) {
    $("botRulesMessage").textContent = error.message;
  }
}

function updateBotMode() {
  if (!$("botEnabled").checked) {
    $("botMode").textContent = "Disabled";
    $("botMode").className = "small-label warning";
  } else if ($("botDryRunOnly").checked) {
    $("botMode").textContent = "Dry-run";
    $("botMode").className = "small-label warning";
  } else {
    $("botMode").textContent = "Live-ready";
    $("botMode").className = "small-label danger";
  }
}

async function loadCandles() {
  $("chartEmpty").textContent = "Loading chart...";
  $("chartEmpty").classList.remove("hidden");
  try {
    const payload = await api(`/api/candles?interval=${state.chartInterval}&limit=300`);
    state.candles = payload.candles || [];
    state.chartViewCount = Math.min(state.chartViewCount, state.candles.length);
    renderChartMeta(payload.symbol, payload.interval);
    drawCandles();
  } catch (error) {
    state.candles = [];
    $("chartMeta").textContent = error.message;
    drawCandles();
  }
}

function renderChartMeta(symbol = "BTCUSDT", interval = state.chartInterval) {
  const visible = Math.min(state.chartViewCount, state.candles.length);
  $("chartMeta").textContent = `${symbol} · ${interval} · ${visible}/${state.candles.length} candles · wheel or +/- to zoom`;
}

function zoomChart(multiplier) {
  if (!state.candles.length) return;
  const nextCount = Math.round(state.chartViewCount * multiplier);
  state.chartViewCount = Math.max(25, Math.min(state.candles.length, nextCount));
  renderChartMeta();
  drawCandles();
}

function resetZoom() {
  state.chartViewCount = Math.min(160, state.candles.length || 160);
  renderChartMeta();
  drawCandles();
}

function drawCandles() {
  const canvas = $("candleChart");
  const wrap = canvas.parentElement;
  const ctx = canvas.getContext("2d");
  const rect = wrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const candles = state.candles.slice(-state.chartViewCount);
  if (!candles.length) {
    $("chartEmpty").classList.remove("hidden");
    return;
  }
  $("chartEmpty").classList.add("hidden");

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 18, right: 86, bottom: 34, left: 14 };
  const volumeHeight = Math.max(54, height * 0.18);
  const chartBottom = height - pad.bottom - volumeHeight - 12;
  const chartHeight = chartBottom - pad.top;
  const chartWidth = width - pad.left - pad.right;

  const levelValues = [state.levels.support, state.levels.resistance].filter(Number.isFinite);
  const priceValues = candles
    .flatMap((item) => [item.high, item.low, item.close, item.ma7, item.ma30, item.ma99].filter(Number.isFinite))
    .concat(levelValues);
  const volumes = candles.map((item) => item.volume);
  const minPrice = Math.min(...priceValues);
  const maxPrice = Math.max(...priceValues);
  const maxVolume = Math.max(...volumes);
  const priceRange = Math.max(maxPrice - minPrice, 1);
  const paddedMin = minPrice - priceRange * 0.08;
  const paddedMax = maxPrice + priceRange * 0.08;
  const paddedRange = paddedMax - paddedMin;
  const step = chartWidth / candles.length;
  const candleWidth = Math.max(2, Math.min(13, step * 0.64));

  const xFor = (index) => pad.left + index * step + step / 2;
  const yFor = (price) => pad.top + ((paddedMax - price) / paddedRange) * chartHeight;
  const volY = height - pad.bottom;

  drawGrid(ctx, width, pad, chartHeight, paddedMax, paddedRange);
  drawVolumes(ctx, candles, xFor, volY, volumeHeight, candleWidth, maxVolume);
  drawCandleBodies(ctx, candles, xFor, yFor, candleWidth);
  drawLine(ctx, candles, "close", xFor, yFor, "#2f5aa8", 1.8);
  drawLine(ctx, candles, "ma7", xFor, yFor, "#b46b07", 1.7);
  drawLine(ctx, candles, "ma30", xFor, yFor, "#7c3aed", 1.7);
  drawLine(ctx, candles, "ma99", xFor, yFor, "#111827", 1.8);
  drawLevel(ctx, yFor, width, pad, state.levels.support, "#12805c", "Support");
  drawLevel(ctx, yFor, width, pad, state.levels.resistance, "#c2415b", "Resistance");
  drawTimeLabels(ctx, candles, pad, width, height);
  drawLastPrice(ctx, candles[candles.length - 1], yFor, width, pad);
}

function drawGrid(ctx, width, pad, chartHeight, paddedMax, paddedRange) {
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#e5ebe4";
  ctx.fillStyle = "#6d746d";
  ctx.font = "12px Segoe UI, Tahoma, sans-serif";

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (chartHeight / 4) * i;
    const price = paddedMax - (paddedRange / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right + 8, y);
    ctx.stroke();
    ctx.fillText(formatUsd(price, 2), width - pad.right + 14, y + 4);
  }
}

function drawVolumes(ctx, candles, xFor, volY, volumeHeight, candleWidth, maxVolume) {
  candles.forEach((item, index) => {
    const x = xFor(index);
    const up = item.close >= item.open;
    const color = up ? "#12805c" : "#c2415b";
    const volumeBarHeight = maxVolume > 0 ? (item.volume / maxVolume) * volumeHeight : 0;
    ctx.globalAlpha = 0.2;
    ctx.fillStyle = color;
    ctx.fillRect(x - candleWidth / 2, volY - volumeBarHeight, candleWidth, volumeBarHeight);
    ctx.globalAlpha = 1;
  });
}

function drawCandleBodies(ctx, candles, xFor, yFor, candleWidth) {
  candles.forEach((item, index) => {
    const x = xFor(index);
    const up = item.close >= item.open;
    const color = up ? "#12805c" : "#c2415b";
    const openY = yFor(item.open);
    const closeY = yFor(item.close);
    const highY = yFor(item.high);
    const lowY = yFor(item.low);
    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(2, Math.abs(closeY - openY));

    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();
    ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
  });
}

function drawLine(ctx, candles, key, xFor, yFor, color, lineWidth) {
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  let hasPoint = false;
  candles.forEach((item, index) => {
    const value = item[key];
    if (!Number.isFinite(value)) return;
    const x = xFor(index);
    const y = yFor(value);
    if (!hasPoint) {
      ctx.moveTo(x, y);
      hasPoint = true;
    } else {
      ctx.lineTo(x, y);
    }
  });
  if (hasPoint) ctx.stroke();
}

function drawLevel(ctx, yFor, width, pad, value, color, label) {
  if (!Number.isFinite(value)) return;
  const y = yFor(value);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.4;
  ctx.setLineDash([7, 5]);
  ctx.beginPath();
  ctx.moveTo(pad.left, y);
  ctx.lineTo(width - pad.right + 8, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.font = "12px Segoe UI, Tahoma, sans-serif";
  ctx.fillText(label, pad.left + 8, y - 6);
}

function drawTimeLabels(ctx, candles, pad, width, height) {
  const first = candles[0];
  const last = candles[candles.length - 1];
  ctx.fillStyle = "#6d746d";
  ctx.font = "12px Segoe UI, Tahoma, sans-serif";
  ctx.fillText(formatChartTime(first.openTime), pad.left, height - 12);
  const lastLabel = formatChartTime(last.openTime);
  ctx.fillText(lastLabel, Math.max(pad.left, width - pad.right - ctx.measureText(lastLabel).width), height - 12);
}

function drawLastPrice(ctx, last, yFor, width, pad) {
  const lastY = yFor(last.close);
  ctx.strokeStyle = last.close >= last.open ? "#12805c" : "#c2415b";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.left, lastY);
  ctx.lineTo(width - pad.right + 8, lastY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = last.close >= last.open ? "#12805c" : "#c2415b";
  ctx.fillRect(width - pad.right + 10, lastY - 11, 72, 22);
  ctx.fillStyle = "#fff";
  ctx.fillText(formatUsd(last.close, 2), width - pad.right + 14, lastY + 4);
}

function formatChartTime(value) {
  const date = new Date(value);
  if (state.chartInterval === "1d") {
    return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  }).format(date);
}

function bindEvents() {
  $("refreshAccount").addEventListener("click", loadAccount);
  $("refreshHistory").addEventListener("click", loadOrderHistory);
  $("refreshSignal").addEventListener("click", loadMarket);
  $("saveBotRules").addEventListener("click", saveBotConfig);
  ["botEnabled", "botDryRunOnly"].forEach((id) => {
    $(id).addEventListener("change", updateBotMode);
  });
  $("zoomIn").addEventListener("click", () => zoomChart(0.72));
  $("zoomOut").addEventListener("click", () => zoomChart(1.35));
  $("zoomReset").addEventListener("click", resetZoom);
  $("candleChart").addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      zoomChart(event.deltaY > 0 ? 1.18 : 0.84);
    },
    { passive: false },
  );

  document.querySelectorAll("[data-interval]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.chartInterval = button.dataset.interval;
      resetZoom();
      document.querySelectorAll("[data-interval]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      await loadCandles();
    });
  });
  window.addEventListener("resize", drawCandles);
}

async function boot() {
  bindEvents();
  if (window.lucide) window.lucide.createIcons();
  await loadHealth();
  await Promise.all([loadMarket(), loadCandles(), loadAccount(), loadOrderHistory(), loadBotConfig()]);
  setInterval(loadMarket, 15000);
  setInterval(loadCandles, 60000);
}

boot();
