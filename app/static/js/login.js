const form = document.querySelector("#login-form");
const errorBox = document.querySelector("[data-testid='login-error']");
const submitButton = document.querySelector("[data-testid='login-submit']");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

document.querySelectorAll(".demo-account").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#username").value = button.dataset.username;
    document.querySelector("#password").value = button.dataset.password;
    errorBox.hidden = true;
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  const username = document.querySelector("#username").value.trim();
  const password = document.querySelector("#password").value;
  if (!username || !password) {
    showError("请输入账号和密码");
    return;
  }
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "正在验证...";
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username, password}),
    });
    const payload = await response.json();
    if (!response.ok) {
      showError(payload.error?.message || "登录失败，请稍后重试");
      return;
    }
    localStorage.setItem("oms_token", payload.data.access_token);
    localStorage.setItem("oms_user", JSON.stringify(payload.data.user));
    window.location.replace("/");
  } catch (error) {
    showError("网络连接异常，请确认服务已启动");
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "进入工作台";
  }
});

