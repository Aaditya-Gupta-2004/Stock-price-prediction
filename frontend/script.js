const backendURL = "http://127.0.0.1:8000"; // change if deployed

let maChart, armaChart, arimaChart, liveChart;
let liveInterval = null;

// =============== AUTOCOMPLETE (Yahoo Finance via FastAPI proxy) ===============
const input = document.getElementById("symbolInput");
const list = document.getElementById("autocompleteList");

// Listen for typing in search box
input.addEventListener("input", async function () {
  const query = this.value.trim();
  list.innerHTML = "";
  if (!query) return;

  try {
    // Hit FastAPI autocomplete endpoint → it calls Yahoo Finance API
    const res = await fetch(`${backendURL}/autocomplete/${encodeURIComponent(query)}`);
    if (!res.ok) return;

    const data = await res.json();
    if (!data.quotes || !data.quotes.length) return;

    // Render suggestion list
    data.quotes.forEach(stock => {
      const div = document.createElement("div");
      div.className = "autocomplete-item";
      const name = stock.shortname || stock.longname || stock.symbol;
      const exch = stock.exchange || "";
      div.innerHTML = `<strong>${stock.symbol}</strong> – ${name} <small>(${exch})</small>`;

      // On click, fill input & fetch prediction
      div.onclick = () => {
        input.value = stock.symbol;
        list.innerHTML = "";
        fetchStockData();
      };

      list.appendChild(div);
    });
  } catch (err) {
    console.error("🔍 Autocomplete fetch failed:", err);
  }
});

// Hide suggestions when clicking outside
document.addEventListener("click", (e) => {
  if (e.target !== input) list.innerHTML = "";
});

// =================== MAIN STOCK FETCHING ===================
async function fetchStockData() {
  const symbol = input.value.trim().toUpperCase();
  const spinner = document.getElementById("loadingSpinner");
  const priceElement = document.getElementById("realtimePrice");

  if (!symbol) {
    alert("⚠️ Please enter a stock symbol!");
    return;
  }

  spinner.style.display = "inline-block";
  priceElement.textContent = "Fetching data...";

  try {
    // Fetch predictions
    const predRes = await fetch(`${backendURL}/predict/${symbol}`);
    if (!predRes.ok) throw new Error("Prediction API failed.");
    const predData = await predRes.json();

    // Fetch real-time price
    const realRes = await fetch(`${backendURL}/realtime/${symbol}`);
    if (!realRes.ok) throw new Error("Real-time API failed.");
    const realData = await realRes.json();

    const price = realData.current;
    const prevClose = realData.prev_close || price;
    const priceChange = price - prevClose;
    const changeClass = priceChange >= 0 ? "price-up" : "price-down";

    priceElement.innerHTML = `Current Price (${symbol}): <span class="${changeClass}">$${price.toFixed(2)}</span>`;

    spinner.style.display = "none";

    renderCharts(predData, symbol, price);
    setupLiveChart(symbol, price);
  } catch (err) {
    console.error(err);
    spinner.style.display = "none";
    alert("❌ Error fetching stock data! Check backend or API key.");
  }
}

// =================== CHART RENDERING ===================
function renderCharts(data, symbol, currentPrice) {
  const labels = Array.from({ length: 30 }, (_, i) => `Day ${i + 1}`);

  const chartOptions = (title, color) => ({
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: title,
          data: data[`${title.split(" ")[0]}_Prediction`],
          borderColor: color,
          borderWidth: 2,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        title: {
          display: true,
          text: `${symbol} - ${title} (Current: $${currentPrice})`,
          color: "#fff",
          font: { size: 18, weight: "600" },
        },
        legend: { labels: { color: "#fff" } },
      },
      scales: {
        x: { ticks: { color: "#adb5bd" } },
        y: { ticks: { color: "#adb5bd" } },
      },
    },
  });

  [maChart, armaChart, arimaChart].forEach((chart) => chart?.destroy());

  maChart = new Chart(document.getElementById("maChart"), chartOptions("MA Prediction", "#0dcaf0"));
  armaChart = new Chart(document.getElementById("armaChart"), chartOptions("ARMA Prediction", "#20c997"));
  arimaChart = new Chart(document.getElementById("arimaChart"), chartOptions("ARIMA Prediction", "#ffc107"));
}

// =================== LIVE CHART ===================
function setupLiveChart(symbol, initialPrice) {
  if (liveChart) liveChart.destroy();
  if (liveInterval) clearInterval(liveInterval);

  const ctx = document.getElementById("liveChart").getContext("2d");
  const data = {
    labels: [new Date().toLocaleTimeString()],
    datasets: [
      {
        label: `${symbol} Live Price`,
        data: [initialPrice],
        borderColor: "#0dcaf0",
        borderWidth: 2,
        fill: false,
      },
    ],
  };

  const config = {
    type: "line",
    data,
    options: {
      responsive: true,
      plugins: {
        title: {
          display: true,
          text: `${symbol} Real-Time Price`,
          color: "#fff",
          font: { size: 18, weight: "600" },
        },
        legend: { labels: { color: "#fff" } },
      },
      scales: {
        x: { ticks: { color: "#adb5bd" } },
        y: { ticks: { color: "#adb5bd" } },
      },
    },
  };

  liveChart = new Chart(ctx, config);

  // Live update every 5 seconds
  liveInterval = setInterval(async () => {
    try {
      const res = await fetch(`${backendURL}/realtime/${symbol}`);
      if (!res.ok) return;
      const liveData = await res.json();
      const price = liveData.current;

      const time = new Date().toLocaleTimeString();
      data.labels.push(time);
      data.datasets[0].data.push(price);

      if (data.labels.length > 20) {
        data.labels.shift();
        data.datasets[0].data.shift();
      }

      liveChart.update();

      const priceElement = document.getElementById("realtimePrice");
      const prevClose = liveData.prev_close || price;
      const priceChange = price - prevClose;
      const changeClass = priceChange >= 0 ? "price-up" : "price-down";
      priceElement.innerHTML = `Current Price (${symbol}): <span class="${changeClass}">$${price.toFixed(2)}</span>`;
    } catch (err) {
      console.error("Live update error:", err);
    }
  }, 5000);
}
