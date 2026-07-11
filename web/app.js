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
      loading: false,
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
    dailyBars() {
      if (!this.summary) return [];
      const [y, m] = this.month.split("-").map(Number);
      const daysInMonth = new Date(y, m, 0).getDate();
      const byDay = {};
      for (const d of this.summary.daily_expenses) byDay[d.day] = Number(d.total);
      const max = Math.max(1, ...Object.values(byDay));
      const bars = [];
      for (let day = 1; day <= daysInMonth; day++) {
        const total = byDay[day] || 0;
        bars.push({
          day,
          total,
          hpct: (total / max) * 100,
          isMax: total === max && total > 0,
          tick: day === 1 || day % 5 === 0,
        });
      }
      return bars;
    },
  },

  methods: {
    fmt(n) {
      return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(n));
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
    currentLimit(categoryId) {
      if (!this.summary) return null;
      const b = this.summary.budgets.find((x) => x.category_id === categoryId);
      return b ? Number(b.budget) : null;
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
      await Promise.all([this.loadSummary(), this.loadCategories(), this.reloadTx()]);
    } finally {
      this.loading = false;
    }
  },
}).mount("#app");
