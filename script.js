const MARKET_DATA_PATH = "market-data.json";
const DASHBOARD_DATA_PATH = "dashboard-data.json";

function formatSignedPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "변동 없음";
  }
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function changeClass(value) {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return "";
  }
  if (numeric > 0) {
    return "up";
  }
  if (numeric < 0) {
    return "down";
  }
  return "";
}

function fearClass(value) {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return "";
  }
  return numeric < 50 ? "down" : "up";
}

function renderMarketCard(card, item) {
  card.querySelector(".market-name").textContent = item.label;
  card.querySelector(".market-value").textContent = item.display_value;

  const changeNode = card.querySelector(".market-change");
  changeNode.textContent = item.change_text || formatSignedPercent(item.change_pct);
  changeNode.classList.remove("up", "down");
  const klass = item.key === "fear_index"
    ? fearClass(item.value)
    : changeClass(item.change_pct);
  if (klass) {
    changeNode.classList.add(klass);
  }

  card.querySelector(".market-note").textContent = item.note || "";
}

function renderStockCard(item, isGradeA = false, scoreKey = "final_score") {
  const scoreValue = item[scoreKey] ?? item.final_score ?? 0;
  return `
    <article class="stock-card ${isGradeA ? "grade-a" : ""}" data-sector="${item.sector_group || item.theme || "기타"}" data-ticker="${item.ticker}">
      <div class="card-top">
        <div>
          <p class="stock-name">${item.name}</p>
          <p class="stock-code">${item.ticker}</p>
        </div>
        <div class="score-chip ${isGradeA ? "" : "muted"}">${scoreValue}점</div>
      </div>

      <div class="meta-list">
        <div class="meta-item">
          <span class="meta-label">현재가</span>
          <strong>${item.current_price?.toLocaleString?.() ?? item.current_price}원</strong>
        </div>
        <div class="meta-item">
          <span class="meta-label">전략</span>
          <strong>${item.strategy_type || "-"}</strong>
        </div>
        <div class="meta-item">
          <span class="meta-label">테마</span>
          <strong>${item.sector_group || item.theme || "기타"}</strong>
        </div>
      </div>

      <div class="card-body">
        <div class="info-block">
          <p class="info-title">이슈 요약</p>
          <p class="info-text">${item.issue_summary || "특이 이슈 없음 (기술적 흐름 기반)"}</p>
        </div>
        <div class="info-block">
          <p class="info-title">핵심 선정 이유</p>
          <p class="info-text">${item.summary_reason || item.reason || "-"}</p>
        </div>
      </div>
    </article>
  `;
}

function renderEmptyCard(message) {
  return `
    <article class="stock-card">
      <div class="card-body">
        <div class="info-block">
          <p class="info-title">안내</p>
          <p class="info-text">${message}</p>
        </div>
      </div>
    </article>
  `;
}

async function loadMarketData() {
  try {
    const response = await fetch(MARKET_DATA_PATH, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    const timestampNode = document.getElementById("page-timestamp");
    if (timestampNode && payload.generated_at) {
      timestampNode.textContent = payload.generated_at;
    }

    for (const item of payload.items || []) {
      const card = document.querySelector(`[data-market-key="${item.key}"]`);
      if (!card) {
        continue;
      }
      renderMarketCard(card, item);
    }
  } catch (error) {
    console.error("시장 지표 로딩 실패:", error);
    document.querySelectorAll(".market-card").forEach((card) => {
      card.querySelector(".market-value").textContent = "-";
      card.querySelector(".market-change").textContent = "불러오기 실패";
      card.querySelector(".market-change").classList.remove("up", "down");
      card.querySelector(".market-note").textContent = "market_data.py 실행 후 market-data.json을 다시 생성해 주세요.";
    });
  }
}

async function loadDashboardData() {
  try {
    const response = await fetch(DASHBOARD_DATA_PATH, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    const timestampNode = document.getElementById("page-timestamp");
    if (timestampNode && payload.generated_at) {
      timestampNode.textContent = payload.generated_at;
    }

    const gradeAGrid = document.getElementById("grade-a-grid");
    const watchGrid = document.getElementById("watch-grid");

    const gradeAHtml = (payload.grade_a || []).length
      ? payload.grade_a.map((item) => renderStockCard(item, true, "final_score")).join("")
      : renderEmptyCard("현재 기준 A급 없음");

    const watchHtml = (payload.watch || []).length
      ? payload.watch.map((item) => renderStockCard(item, false, "observation_score")).join("")
      : renderEmptyCard("관찰 후보 없음");

    if (gradeAGrid) {
      gradeAGrid.innerHTML = gradeAHtml;
    }
    if (watchGrid) {
      watchGrid.innerHTML = watchHtml;
    }
  } catch (error) {
    console.error("추천 결과 로딩 실패:", error);
  }
}

Promise.all([loadMarketData(), loadDashboardData()]);
