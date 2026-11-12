const state = {
  user: null,
  products: [],
  categories: [],
  cart: new Map(),
  orders: [],
  orderFilter: "",
  draftKey: null,
  loading: false,
};

const statusLabels = {
  CREATED: "待拣货",
  PICKING: "拣货中",
  SHIPPED: "已发货",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
};

const statusActions = {
  CREATED: {status: "PICKING", label: "开始拣货"},
  PICKING: {status: "SHIPPED", label: "确认发货"},
  SHIPPED: {status: "COMPLETED", label: "确认完成"},
};

const roleLabels = {
  admin: "系统管理员",
  operator: "履约专员",
  viewer: "只读审核",
};

function token() {
  return localStorage.getItem("oms_token");
}

function redirectToLogin() {
  localStorage.removeItem("oms_token");
  localStorage.removeItem("oms_user");
  window.location.replace("/login");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {...options, headers});
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("登录已过期");
  }
  if (!response.ok) {
    const message = payload?.error?.message || `请求失败 (${response.status})`;
    const apiError = new Error(message);
    apiError.code = payload?.error?.code;
    throw apiError;
  }
  return payload;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name, className = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.appendChild(use);
  return svg;
}

function formatMoney(value) {
  return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

let toastTimer = null;
function showToast(message, tone = "success") {
  const toast = document.querySelector("#toast");
  document.querySelector("#toast-message").textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function setBusy(button, busy, label) {
  if (!button) return;
  button.disabled = busy;
  const text = button.querySelector("span");
  if (text && label) text.textContent = label;
}

async function loadIdentity() {
  const payload = await api("/api/v1/auth/me");
  state.user = payload.data;
  const name = state.user.display_name || state.user.username;
  document.querySelector("#user-name").textContent = name;
  document.querySelector("#user-role").textContent =
    roleLabels[state.user.role] || state.user.role;
  document.querySelector("#user-avatar").textContent = name.slice(0, 1).toUpperCase();
  document.body.dataset.role = state.user.role;
  document.body.classList.toggle("is-viewer", state.user.role === "viewer");
}

async function loadSummary() {
  const payload = await api("/api/v1/dashboard/summary");
  const data = payload.data;
  document.querySelector("#kpi-orders-today").textContent = data.orders_today;
  document.querySelector("#kpi-orders-total").textContent = data.orders_total;
  document.querySelector("#kpi-pending-orders").textContent = data.pending_orders;
  document.querySelector("#kpi-low-stock").textContent = data.low_stock_count;
  document.querySelector("#kpi-fulfillment-rate").textContent =
    Number(data.fulfillment_rate).toFixed(1);
  document.querySelector("#nav-order-count").textContent = data.pending_orders;
}

async function loadProducts() {
  const search = document.querySelector("#product-search").value.trim();
  const category = document.querySelector("#category-filter").value;
  const params = new URLSearchParams({page_size: "100"});
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  const payload = await api(`/api/v1/products?${params.toString()}`);
  state.products = payload.data.items;
  state.categories = payload.data.categories;
  renderCategories();
  renderProducts();
  renderCart();
}

function renderCategories() {
  const select = document.querySelector("#category-filter");
  const current = select.value;
  select.replaceChildren(new Option("全部分类", ""));
  state.categories.forEach((category) => {
    select.appendChild(new Option(category, category));
  });
  select.value = current;
}

function renderProducts() {
  const body = document.querySelector("#product-table-body");
  body.replaceChildren();
  if (!state.products.length) {
    const row = document.createElement("tr");
    const cell = element("td", "empty-table", "没有匹配的商品");
    cell.colSpan = 5;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  state.products.forEach((product) => {
    const row = document.createElement("tr");
    row.dataset.productId = String(product.id);
    row.dataset.testid = "product-row";

    const productCell = document.createElement("td");
    const productMain = element("div", "product-main");
    const productMark = element("span", "product-mark", product.name.slice(0, 1));
    const productCopy = element("span", "product-copy");
    productCopy.appendChild(element("strong", "", product.name));
    productCopy.appendChild(element("small", "", product.sku));
    productMain.append(productMark, productCopy);
    productCell.appendChild(productMain);

    const categoryCell = element("td", "", product.category);
    const priceCell = element("td", "align-right numeric", `¥${formatMoney(product.price)}`);
    const stockCell = document.createElement("td");
    stockCell.className = "align-right";
    const stockBadge = element(
      "span",
      `stock-badge ${product.low_stock ? "is-low" : ""}`,
      `${product.stock} 件`
    );
    stockCell.appendChild(stockBadge);

    const actionCell = document.createElement("td");
    actionCell.className = "align-right";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-compact button-secondary can-write";
    button.dataset.testid = "add-product";
    button.dataset.productId = String(product.id);
    button.title = `将 ${product.name} 加入待提交订单`;
    button.append(icon("plus"), element("span", "", "加入"));
    actionCell.appendChild(button);
    row.append(productCell, categoryCell, priceCell, stockCell, actionCell);
    body.appendChild(row);
  });
}

function cartTotal() {
  let total = 0;
  state.cart.forEach((quantity, productId) => {
    const product = state.products.find((item) => item.id === productId);
    if (product) total += Number(product.price) * quantity;
  });
  return total;
}

function renderCart() {
  const container = document.querySelector("#cart-lines");
  const submit = document.querySelector("#submit-order-button");
  container.replaceChildren();
  if (!state.cart.size) {
    const empty = element("div", "cart-empty");
    empty.dataset.testid = "cart-empty";
    empty.append(
      icon("cart"),
      element("strong", "", "订单还是空的"),
      element("span", "", "从左侧商品列表加入商品")
    );
    container.appendChild(empty);
    submit.disabled = true;
  } else {
    state.cart.forEach((quantity, productId) => {
      const product = state.products.find((item) => item.id === productId);
      if (!product) return;
      const line = element("div", "cart-line");
      line.dataset.testid = "cart-line";
      line.dataset.productId = String(product.id);
      const copy = element("div", "cart-line-copy");
      copy.append(
        element("strong", "", product.name),
        element("small", "", `¥${formatMoney(product.price)} / 件`)
      );
      const stepper = element("div", "stepper");
      const minus = document.createElement("button");
      minus.type = "button";
      minus.className = "stepper-button";
      minus.dataset.action = "decrease";
      minus.dataset.productId = String(product.id);
      minus.setAttribute("aria-label", `减少 ${product.name} 数量`);
      minus.appendChild(icon("minus"));
      const amount = element("span", "stepper-value", String(quantity));
      amount.dataset.testid = "cart-qty";
      const plus = document.createElement("button");
      plus.type = "button";
      plus.className = "stepper-button";
      plus.dataset.action = "increase";
      plus.dataset.productId = String(product.id);
      plus.setAttribute("aria-label", `增加 ${product.name} 数量`);
      plus.appendChild(icon("plus"));
      stepper.append(minus, amount, plus);
      line.append(copy, stepper);
      container.appendChild(line);
    });
    submit.disabled = false;
  }
  document.querySelector("#cart-total").textContent = formatMoney(cartTotal());
  document.querySelector("#clear-cart-button").disabled = !state.cart.size;
}

function addToCart(productId) {
  const product = state.products.find((item) => item.id === productId);
  if (!product) return;
  const next = (state.cart.get(productId) || 0) + 1;
  if (next > Math.min(product.stock, 99)) {
    showToast("数量已达到当前可购买上限", "warning");
    return;
  }
  state.cart.set(productId, next);
  state.draftKey = null;
  renderCart();
  showToast(`${product.name} 已加入订单`);
}

function changeQuantity(productId, delta) {
  const product = state.products.find((item) => item.id === productId);
  const next = (state.cart.get(productId) || 0) + delta;
  if (next <= 0) {
    state.cart.delete(productId);
  } else if (product && next <= Math.min(product.stock, 99)) {
    state.cart.set(productId, next);
  } else {
    showToast("库存不足，无法继续增加", "warning");
    return;
  }
  state.draftKey = null;
  renderCart();
}

async function submitOrder() {
  if (!state.cart.size || state.loading) return;
  const button = document.querySelector("#submit-order-button");
  state.loading = true;
  setBusy(button, true, "正在提交...");
  try {
    if (!state.draftKey) {
      state.draftKey = crypto.randomUUID();
    }
    const items = Array.from(state.cart.entries()).map(([productId, quantity]) => ({
      product_id: productId,
      quantity,
    }));
    const payload = await api("/api/v1/orders", {
      method: "POST",
      headers: {"Idempotency-Key": state.draftKey},
      body: JSON.stringify({
        items,
        remark: document.querySelector("#order-remark").value.trim(),
      }),
    });
    showToast(`订单 ${payload.data.order_no} 已创建`);
    state.cart.clear();
    state.draftKey = null;
    document.querySelector("#order-remark").value = "";
    renderCart();
    await Promise.all([loadProducts(), loadOrders(), loadSummary()]);
  } catch (error) {
    showToast(error.message, "error");
    if (error.code === "ORDER_STOCK_INSUFFICIENT") {
      await loadProducts();
    }
  } finally {
    state.loading = false;
    setBusy(button, false, "提交订单");
    renderCart();
  }
}

async function loadOrders() {
  const params = new URLSearchParams({page_size: "50"});
  if (state.orderFilter) params.set("status", state.orderFilter);
  const payload = await api(`/api/v1/orders?${params.toString()}`);
  state.orders = payload.data.items;
  renderOrders();
}

function renderOrders() {
  const body = document.querySelector("#order-table-body");
  body.replaceChildren();
  if (!state.orders.length) {
    const row = document.createElement("tr");
    const cell = element("td", "empty-table", "当前筛选下没有订单");
    cell.colSpan = 7;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  state.orders.forEach((order) => {
    const row = document.createElement("tr");
    row.dataset.testid = "order-row";
    row.dataset.orderId = String(order.id);
    row.appendChild(element("td", "order-number", order.order_no));
    row.appendChild(element("td", "", order.customer || "-"));
    row.appendChild(element("td", "align-right numeric", String(order.item_count)));
    row.appendChild(element("td", "align-right numeric", `¥${formatMoney(order.total)}`));
    const statusCell = document.createElement("td");
    statusCell.appendChild(
      element("span", `status-pill status-${order.status.toLowerCase()}`, statusLabels[order.status] || order.status)
    );
    row.appendChild(statusCell);
    row.appendChild(element("td", "muted-cell", formatDateTime(order.created_at)));

    const actions = document.createElement("td");
    actions.className = "align-right order-actions";
    const action = statusActions[order.status];
    if (action) {
      const advance = document.createElement("button");
      advance.type = "button";
      advance.className = "button button-compact button-secondary can-write";
      advance.dataset.testid = "advance-order";
      advance.dataset.orderId = String(order.id);
      advance.dataset.nextStatus = action.status;
      advance.textContent = action.label;
      actions.appendChild(advance);
    }
    if (["CREATED", "PICKING"].includes(order.status)) {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "button button-compact button-ghost-danger can-write";
      cancel.dataset.testid = "cancel-order";
      cancel.dataset.orderId = String(order.id);
      cancel.textContent = "取消";
      actions.appendChild(cancel);
    }
    row.appendChild(actions);
    body.appendChild(row);
  });
}

async function advanceOrder(orderId, nextStatus) {
  try {
    await api(`/api/v1/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({status: nextStatus}),
    });
    showToast(`订单已更新为${statusLabels[nextStatus]}`);
    await Promise.all([loadOrders(), loadSummary()]);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function cancelOrder(orderId) {
  if (!window.confirm("确认取消该订单并回补库存？")) return;
  try {
    await api(`/api/v1/orders/${orderId}/cancel`, {method: "POST"});
    showToast("订单已取消，库存已回补");
    await Promise.all([loadOrders(), loadProducts(), loadSummary()]);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function refreshAll() {
  const button = document.querySelector("#refresh-button");
  button.classList.add("is-spinning");
  try {
    await Promise.all([loadSummary(), loadProducts(), loadOrders()]);
    showToast("数据已刷新");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    window.setTimeout(() => button.classList.remove("is-spinning"), 500);
  }
}

let searchTimer = null;
function scheduleProductSearch() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    loadProducts().catch((error) => showToast(error.message, "error"));
  }, 260);
}

function bindEvents() {
  document.querySelector("#logout-button").addEventListener("click", () => {
    localStorage.removeItem("oms_token");
    localStorage.removeItem("oms_user");
    redirectToLogin();
  });
  document.querySelector("#refresh-button").addEventListener("click", refreshAll);
  document.querySelector("#new-order-button").addEventListener("click", () => {
    state.cart.clear();
    state.draftKey = null;
    renderCart();
    document.querySelector("#product-search").focus();
    document.querySelector("#inventory").scrollIntoView({behavior: "smooth", block: "start"});
  });
  document.querySelector("#product-search").addEventListener("input", scheduleProductSearch);
  document.querySelector("#category-filter").addEventListener("change", () => {
    loadProducts().catch((error) => showToast(error.message, "error"));
  });
  document.querySelector("#product-table-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-testid='add-product']");
    if (button) addToCart(Number(button.dataset.productId));
  });
  document.querySelector("#cart-lines").addEventListener("click", (event) => {
    const button = event.target.closest(".stepper-button");
    if (!button) return;
    changeQuantity(
      Number(button.dataset.productId),
      button.dataset.action === "increase" ? 1 : -1
    );
  });
  document.querySelector("#clear-cart-button").addEventListener("click", () => {
    state.cart.clear();
    state.draftKey = null;
    renderCart();
  });
  document.querySelector("#submit-order-button").addEventListener("click", submitOrder);
  document.querySelector("#order-filter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-status]");
    if (!button) return;
    document.querySelectorAll("#order-filter button").forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    state.orderFilter = button.dataset.status;
    loadOrders().catch((error) => showToast(error.message, "error"));
  });
  document.querySelector("#order-table-body").addEventListener("click", (event) => {
    const advance = event.target.closest("[data-testid='advance-order']");
    if (advance) {
      advanceOrder(Number(advance.dataset.orderId), advance.dataset.nextStatus);
      return;
    }
    const cancel = event.target.closest("[data-testid='cancel-order']");
    if (cancel) cancelOrder(Number(cancel.dataset.orderId));
  });
}

async function initialize() {
  if (!token()) {
    redirectToLogin();
    return;
  }
  document.querySelector("#current-date").textContent = new Date().toLocaleDateString(
    "zh-CN",
    {year: "numeric", month: "long", day: "numeric", weekday: "long"}
  );
  bindEvents();
  try {
    await loadIdentity();
    await Promise.all([loadSummary(), loadProducts(), loadOrders()]);
  } catch (error) {
    if (error.message !== "登录已过期") {
      showToast(error.message, "error");
    }
  }
}

initialize();

