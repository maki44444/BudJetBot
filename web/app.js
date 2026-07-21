const { createApp } = Vue;

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

createApp({
  data() {
    return {
      tab: "dashboard",
      month: currentMonth(),
      summary: null,
      tx: { items: [], total: 0 },
      txOffset: 0,
      txPageSize: 50,
      filterCategory: null,
      categories: { expense: [], income: [] },
      limitDrafts: {},
      settings: { oneoff_threshold: null, reminder_enabled: true },
      suggest: null,     // предпросмотр автоподбора лимитов
      suggestDays: 0,    // сколько дней ведётся учёт (для предупреждения)
      theme: document.documentElement.dataset.theme || "light",
      loading: false,
      chartDays: null,      // null = месяц, 7 или 14 = скользящее окно от сегодня
      dailyExtra: [],       // данные для окон 7/14 дней (грузятся отдельно)
      goals: [],
      newGoal: { icon: "🎯", name: "", target_amount: null, target_date: "" },
      contributeDrafts: {},
      showArchived: false,
    };
  },

  computed: {
    monthLabel() {
      const [y, m] = this.month.split("-").map(Number);
      return `${MONTHS[m - 1]} ${y}`;
    },
    balance() {
      if (!this.summary) return 0;
      return this.summary.totals.income - this.summary.totals.expense;
    },
    maxExpense() {
      if (!this.summary || !this.summary.expense_breakdown.length) return 1;
      return Math.max(...this.summary.expense_breakdown.map((r) => Number(r.total)));
    },
    expenseDelta() {
      return this.pctDelta(this.summary?.totals.expense, this.summary?.prev.totals.expense);
    },
    incomeDelta() {
      return this.pctDelta(this.summary?.totals.income, this.summary?.prev.totals.income);
    },
    chartDates() {
      // Даты окна графика (ISO-строки): месяц целиком или последние N дней
      const pad = (n) => String(n).padStart(2, "0");
      const dates = [];
      if (!this.chartDays) {
        const [y, m] = this.month.split("-").map(Number);
        const daysInMonth = new Date(y, m, 0).getDate();
        for (let d = 1; d <= daysInMonth; d++) dates.push(`${y}-${pad(m)}-${pad(d)}`);
      } else {
        const today = new Date();
        for (let i = this.chartDays - 1; i >= 0; i--) {
          const dt = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
          dates.push(`${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`);
        }
      }
      return dates;
    },
    dailyView() {
      const items = this.chartDays ? this.dailyExtra : (this.summary ? this.summary.daily_expenses : []);
      const byDate = {};
      for (const it of items) byDate[it.date] = { expense: Number(it.expense), income: Number(it.income) };
      const dates = this.chartDates;
      const maxExpense = Math.max(0, ...dates.map((d) => byDate[d]?.expense || 0));
      const maxAny = Math.max(maxExpense, ...dates.map((d) => byDate[d]?.income || 0));
      const top = this.niceCeil(maxAny);
      const hpct = (v) => (v > 0 ? Math.max((v / top) * 100, 2) : 0);
      const bars = dates.map((iso) => {
        const [y, m, d] = iso.split("-").map(Number);
        const date = new Date(y, m - 1, d);
        const { expense = 0, income = 0 } = byDate[iso] || {};
        let tickLabel = "";
        if (this.chartDays === 7) {
          tickLabel = date.toLocaleDateString("ru-RU", { weekday: "short" });
        } else if (this.chartDays === 14) {
          tickLabel = String(d);
        } else if (d === 1 || d % 5 === 0) {
          tickLabel = String(d);
        }
        let title = date.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" })
          + " — расходы " + this.fmt(expense) + " ₽";
        if (income > 0) title += ", доходы " + this.fmt(income) + " ₽";
        return {
          key: iso,
          expense,
          income,
          hExp: hpct(expense),
          hInc: hpct(income),
          isMax: expense === maxExpense && expense > 0,
          tickLabel,
          title,
        };
      });
      return {
        bars,
        hasData: maxAny > 0,
        grid: top > 1 ? [{ value: top / 2, pct: 50 }, { value: top, pct: 100 }] : [],
      };
    },
    activeGoals() {
      return this.goals.filter((g) => !g.is_archived);
    },
    archivedGoals() {
      return this.goals.filter((g) => g.is_archived);
    },
  },

  methods: {
    fmt(n) {
      return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(n));
    },
    niceCeil(v) {
      // «Круглая» верхняя граница шкалы чуть выше максимума
      if (v <= 0) return 1;
      const pow = Math.pow(10, Math.floor(Math.log10(v)));
      for (const mult of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
        if (mult * pow >= v) return mult * pow;
      }
      return v;
    },
    async setChartDays(days) {
      this.chartDays = days;
      if (days) {
        this.dailyExtra = (await this.api(`/api/daily?days=${days}`)).items;
      }
    },
    pctDelta(cur, prev) {
      cur = Number(cur); prev = Number(prev);
      if (!prev) return null;   // прошлый месяц пуст — сравнивать не с чем
      const pct = Math.round(((cur - prev) / prev) * 100);
      return { pct, text: (pct >= 0 ? "+" : "−") + Math.abs(pct) + "%" };
    },
    catDelta(row) {
      const prevMap = this.summary?.prev.expense_by_category || {};
      if (!Object.keys(prevMap).length) return null;  // прошлый месяц пуст — сравнивать не с чем
      const prev = prevMap[String(row.category_id)];
      if (prev === undefined) return { text: "новое", cls: "muted" };
      const d = this.pctDelta(row.total, prev);
      if (!d) return null;
      return { text: d.text, cls: d.pct > 0 ? "delta-bad" : "delta-good" };
    },
    shortDate(iso) {
      const d = new Date(iso);
      return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
    },
    barWidth(total) {
      return (Number(total) / this.maxExpense) * 100 + "%";
    },
    budgetPct(b) {
      return b.budget > 0 ? Math.round((Number(b.spent) / Number(b.budget)) * 100) : 0;
    },
    budgetState(b) {
      const pct = this.budgetPct(b);
      if (pct >= 100) return "critical";
      if (pct >= 80) return "warning";
      return "ok";
    },
    budgetProj(b) {
      // Прогнозный % лимита к концу месяца; показываем только если грозит превышение
      const f = this.summary?.forecast;
      if (!f) return null;
      const spent = Number(b.spent), budget = Number(b.budget);
      if (!budget || spent >= budget) return null;  // уже превышен — прогноз не нужен
      const projection = (spent / f.days_elapsed) * f.days_in_month;
      const projPct = Math.round((projection / budget) * 100);
      return projPct > 100 ? projPct : null;
    },
    budgetOf(categoryId) {
      if (!this.summary) return null;
      return this.summary.budgets.find((x) => x.category_id === categoryId) || null;
    },
    currentLimit(categoryId) {
      const b = this.budgetOf(categoryId);
      return b ? Number(b.budget) : null;
    },
    async loadSuggest() {
      const data = await this.api("/api/limits/suggest");
      if (!data.items.length) {
        alert("Пока мало данных для подбора — веди учёт ещё немного.");
        return;
      }
      this.suggestDays = data.tracking_days;
      this.suggest = data.items.map((s) => ({ ...s, checked: true }));
    },
    async applySuggest() {
      const items = this.suggest
        .filter((s) => s.checked && s.suggested > 0)
        .map((s) => ({ category_id: s.category_id, amount: Number(s.suggested) }));
      if (!items.length) {
        this.suggest = null;
        return;
      }
      await this.api("/api/limits/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      this.suggest = null;
      await this.loadSummary();
    },
    async toggleMode(categoryId) {
      const b = this.budgetOf(categoryId);
      if (!b) return;
      await this.api("/api/limits", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category_id: categoryId,
          mode: b.mode === "auto" ? "manual" : "auto",
        }),
      });
      await this.loadSummary();
    },

    async api(path, options = {}) {
      const resp = await fetch(path, { credentials: "same-origin", ...options });
      if (resp.status === 401) {
        location.href = "/login";
        throw new Error("unauthorized");
      }
      if (!resp.ok) {
        let detail = resp.statusText;
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        alert("Ошибка: " + detail);
        throw new Error(detail);
      }
      return resp.json();
    },

    async loadSummary() {
      this.summary = await this.api(`/api/summary?month=${this.month}`);
    },
    async loadCategories() {
      this.categories = await this.api("/api/categories");
    },
    async loadSettings() {
      this.settings = await this.api("/api/settings");
    },
    async saveSettings(patch) {
      if (patch.oneoff_threshold !== undefined
          && (!patch.oneoff_threshold || patch.oneoff_threshold <= 0)) {
        alert("Порог должен быть больше нуля");
        return;
      }
      await this.api("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
    },
    async toggleOneoff(t) {
      await this.api(`/api/transactions/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_oneoff: !t.is_oneoff }),
      });
      t.is_oneoff = !t.is_oneoff;
      await this.loadSummary();  // прогноз пересчитывается
    },
    async loadTx(append = false) {
      const params = new URLSearchParams({
        month: this.month,
        limit: this.txPageSize,
        offset: this.txOffset,
      });
      if (this.filterCategory) params.set("category_id", this.filterCategory);
      const data = await this.api(`/api/transactions?${params}`);
      this.tx.total = data.total;
      this.tx.items = append ? this.tx.items.concat(data.items) : data.items;
    },
    async reloadTx() {
      this.txOffset = 0;
      await this.loadTx(false);
    },
    async loadMoreTx() {
      this.txOffset += this.txPageSize;
      await this.loadTx(true);
    },

    async reloadAll() {
      this.loading = true;
      try {
        await Promise.all([this.loadSummary(), this.reloadTx()]);
      } finally {
        this.loading = false;
      }
    },

    prevMonth() { this.shiftMonth(-1); },
    nextMonth() { this.shiftMonth(1); },
    shiftMonth(delta) {
      let [y, m] = this.month.split("-").map(Number);
      m += delta;
      if (m < 1) { m = 12; y -= 1; }
      if (m > 12) { m = 1; y += 1; }
      this.month = `${y}-${String(m).padStart(2, "0")}`;
    },

    async changeCategory(t, event) {
      const categoryId = Number(event.target.value);
      await this.api(`/api/transactions/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: categoryId }),
      });
      await this.reloadAll();
    },

    async removeTx(t) {
      const sign = t.type === "income" ? "+" : "−";
      if (!confirm(`Удалить запись ${sign}${this.fmt(t.amount)} ₽?`)) return;
      await this.api(`/api/transactions/${t.id}`, { method: "DELETE" });
      await this.reloadAll();
    },

    async saveLimit(categoryId) {
      const amount = this.limitDrafts[categoryId];
      if (amount === undefined || amount === "" || amount === null || amount < 0) {
        alert("Введи сумму (0 — снять лимит)");
        return;
      }
      await this.api("/api/limits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: categoryId, amount: Number(amount) }),
      });
      delete this.limitDrafts[categoryId];
      await this.loadSummary();
    },

    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = this.theme;
      localStorage.setItem("theme", this.theme);
    },

    async loadGoals() {
      const data = await this.api("/api/goals?include_archived=true");
      this.goals = data.items;
    },
    goalPct(g) {
      return Number(g.target_amount) > 0
        ? Math.round((Number(g.saved) / Number(g.target_amount)) * 100)
        : 0;
    },
    fullDate(iso) {
      const d = new Date(iso);
      return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
    },
    goalDeadlineText(g) {
      if (!g.target_date || g.is_completed) return null;
      const daysLeft = Math.round((new Date(g.target_date) - new Date()) / 86400000);
      const remaining = Number(g.target_amount) - Number(g.saved);
      if (daysLeft > 0 && remaining > 0) {
        const monthly = remaining / (daysLeft / 30.44);
        return `к ${this.fullDate(g.target_date)} — откладывай ~${this.fmt(monthly)} ₽/мес`;
      }
      return `срок (${this.fullDate(g.target_date)}) наступил`;
    },
    async createGoal() {
      const name = (this.newGoal.name || "").trim();
      if (!name) { alert("Укажи название цели"); return; }
      if (!this.newGoal.target_amount || this.newGoal.target_amount <= 0) {
        alert("Сумма должна быть больше нуля");
        return;
      }
      await this.api("/api/goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          icon: this.newGoal.icon || "🎯",
          target_amount: Number(this.newGoal.target_amount),
          target_date: this.newGoal.target_date || null,
        }),
      });
      this.newGoal = { icon: "🎯", name: "", target_amount: null, target_date: "" };
      await this.loadGoals();
    },
    async contributeGoal(g, sign) {
      const raw = this.contributeDrafts[g.id];
      if (!raw || Number(raw) <= 0) { alert("Введи сумму больше нуля"); return; }
      await this.api(`/api/goals/${g.id}/contribute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: Number(raw) * sign }),
      });
      delete this.contributeDrafts[g.id];
      await this.loadGoals();
    },
    async archiveGoal(g) {
      await this.api(`/api/goals/${g.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_archived: !g.is_archived }),
      });
      await this.loadGoals();
    },
    async removeGoal(g) {
      if (!confirm(`Удалить цель «${g.name}»? Это нельзя отменить.`)) return;
      await this.api(`/api/goals/${g.id}`, { method: "DELETE" });
      await this.loadGoals();
    },
    async logout() {
      await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
      location.href = "/login";
    },
  },

  watch: {
    month() { this.reloadAll(); },
  },

  async mounted() {
    this.loading = true;
    try {
      await Promise.all([
        this.loadSummary(), this.loadCategories(), this.reloadTx(), this.loadSettings(), this.loadGoals(),
      ]);
    } finally {
      this.loading = false;
    }
  },
}).mount("#app");
