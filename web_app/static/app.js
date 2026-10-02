const $ = (selector) => document.querySelector(selector);
const state = { dataset: null, report: null, selected: null, sessionId: null, chatBusy: false };

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error("تعذّر قراءة رد الخادم المحلي"); }
  if (!response.ok) throw new Error(data.error || "تعذّر إكمال الطلب");
  return data;
}

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function setStatus(message, ready) {
  const status = $("#connection-status");
  status.classList.toggle("ready", !!ready);
  status.querySelector("span:last-child").textContent = message;
}

async function refreshStatus() {
  try {
    const status = await request("/api/status");
    setStatus(status.message, status.ready);
  } catch { setStatus("الخادم المحلي غير متصل", false); }
}

async function loadDatasets() {
  const data = await request("/api/datasets");
  const select = $("#dataset-select");
  select.replaceChildren();
  for (const item of data.datasets) {
    const option = node("option", "", `${item.data_file} · ${item.students} طالبًا`);
    option.value = item.data_file;
    select.append(option);
  }
  if (!data.datasets.length) throw new Error("لا توجد ملفات JSON داخل مجلد data");
  state.dataset = data.datasets[0].data_file;
  select.value = state.dataset;
  applyDatasetDates(data.datasets[0]);
  select.addEventListener("change", () => {
    const item = data.datasets.find((entry) => entry.data_file === select.value);
    state.dataset = item.data_file;
    applyDatasetDates(item);
    loadAnalysis();
  });
  await loadAnalysis();
}

function applyDatasetDates(item) {
  if (item.period) {
    $("#period-start").value = item.period.start;
    $("#period-end").value = item.period.end;
  }
}

async function loadAnalysis() {
  const button = $("#analyze-btn");
  button.disabled = true;
  button.textContent = "جارٍ الفحص…";
  try {
    const params = new URLSearchParams({ data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value });
    state.report = await request(`/api/analysis?${params}`);
    renderReport();
  } catch (error) {
    $("#cases-list").replaceChildren(node("p", "empty", error.message));
    $("#attendance-chart").replaceChildren(node("p", "empty", "تعذّر عرض الحضور للفترة المختارة."));
  } finally {
    button.disabled = false;
    button.innerHTML = 'تحديث التحليل <span aria-hidden="true">↗</span>';
  }
}

function renderReport() {
  const summary = state.report.summary;
  $("#stat-students").textContent = summary.students;
  $("#stat-candidates").textContent = summary.candidates;
  $("#stat-unresolved").textContent = summary.unresolved;
  $("#stat-present").textContent = summary.attendance.present_student_days;
  const chart = $("#attendance-chart");
  chart.replaceChildren();
  if (!summary.attendance.by_date.length) chart.append(node("p", "empty", "لا توجد تواريخ حضور مسجلة لهذه الفترة."));
  for (const day of summary.attendance.by_date) {
    const row = node("div", "attendance-day");
    const date = node("time", "", day.date);
    date.dateTime = day.date;
    const track = node("div", "bar-track");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", `${day.date}: ${day.present} حاضر، ${day.absent} غائب، ${day.unrecorded} غير مسجل، ${day.missing_record} سجل مفقود`);
    for (const [key, cls] of [["present", "bar-present"], ["absent", "bar-absent"], ["unrecorded", "bar-unknown"], ["missing_record", "bar-unknown"]]) {
      if (!day[key]) continue;
      const bar = node("span", cls);
      bar.style.width = `${100 * day[key] / summary.students}%`;
      track.append(bar);
    }
    row.append(date, track, node("span", "attendance-numbers", `${day.present} / ${day.absent}`));
    chart.append(row);
  }
  const cases = [...state.report.candidates, ...state.report.unresolved];
  $("#case-count").textContent = `${cases.length} حالات`;
  const list = $("#cases-list");
  list.replaceChildren();
  if (!cases.length) list.append(node("p", "empty", "لا توجد حالات للمراجعة في هذه الفترة."));
  for (const item of cases) {
    const row = node("button", `case-row ${item.priority === "needs_verification" ? "unresolved" : item.priority}`);
    row.type = "button";
    row.dataset.student = item.student_id;
    row.append(node("span", "case-initial", item.student_id.split("-").at(-1)));
    const copy = node("span", "case-copy");
    copy.append(node("strong", "", `${item.alias} · ${item.student_id}`));
    copy.append(node("span", "", item.alerts.length ? item.alerts.map(alertName).join(" · ") : "سجل حضور يحتاج تحققًا"));
    row.append(copy, node("span", `priority-tag ${priorityClass(item)}`, priorityName(item)), node("span", "case-arrow", "‹"));
    row.addEventListener("click", () => selectCase(item.student_id));
    list.append(row);
  }
  selectCase(cases.some(item => item.student_id === state.selected) ? state.selected : cases[0]?.student_id);
}

function priorityClass(item) { return item.priority === "high" ? "high" : item.priority === "standard" ? "standard" : "neutral"; }
function priorityName(item) { return item.priority === "high" ? "أولوية عالية" : item.priority === "standard" ? "أولوية عادية" : "تحتاج تحققًا"; }
function alertName(item) { return item.type === "score_drop" ? `تراجع ${item.subject}` : "غياب مسجل"; }

function block(title, lines) {
  const box = node("div", "detail-block");
  box.append(node("strong", "", title));
  const items = Array.isArray(lines) ? lines : [lines];
  if (items.length > 1) {
    const list = node("ul");
    for (const line of items) list.append(node("li", "", line));
    box.append(list);
  } else box.append(node("p", "", items[0] || "لا توجد معلومات."));
  return box;
}

function selectCase(studentId) {
  state.selected = studentId || null;
  for (const row of document.querySelectorAll(".case-row")) row.classList.toggle("selected", row.dataset.student === studentId);
  const item = [...state.report.candidates, ...state.report.unresolved].find(entry => entry.student_id === studentId);
  const details = $("#detail-body");
  details.replaceChildren();
  $("#review-form").hidden = !item;
  $("#review-feedback").textContent = "";
  if (!item) {
    $("#detail-title").textContent = "لا توجد حالة محددة";
    $("#detail-priority").textContent = "—";
    details.append(node("p", "empty", "اختر فترة أخرى أو ملف بيانات آخر."));
    return;
  }
  $("#detail-title").textContent = `${item.alias} · ${item.student_id}`;
  $("#detail-priority").textContent = priorityName(item);
  $("#detail-priority").className = `priority-tag ${priorityClass(item)}`;
  const attendance = item.attendance;
  details.append(block("الحضور خلال الفترة", `${attendance.present} حاضر، ${attendance.absent} غائب، ${attendance.unrecorded} غير مسجل${attendance.missing_record_dates.length ? `، ${attendance.missing_record_dates.length} سجل مفقود` : ""}.`));
  if (item.alerts.length) details.append(block("المؤشرات المؤكدة", item.alerts.map(signal => {
    if (signal.type === "absence_in_five_school_days") return `${signal.count} غياب مسجل في نافذة خمسة أيام: ${signal.dates.join("، ")}. المصدر: الحضور.`;
    return `انخفاض ${signal.subject} من ${signal.previous.percent}% (${signal.previous.date}) إلى ${signal.current.percent}% (${signal.current.date})، بفارق ${signal.drop_percentage_points} نقطة. المصدر: التقييمات.`;
  })));
  details.append(block("المتابعة السابقة", item.previous_followups.length ? item.previous_followups.map(f => `${f.id} · ${f.date} · ${f.topic}: ${f.outcome}`) : "لا توجد متابعة سابقة في الملف حتى نهاية الفترة."));
  if (item.missing_information.length) details.append(block("معلومات تحتاج تحققًا", item.missing_information.map(info => {
    if (info.startsWith("Attendance unrecorded on: ")) return `حضور غير مسجل في ${info.split(": ")[1]}`;
    if (info.startsWith("Attendance row missing on: ")) return `سجل حضور مفقود في ${info.split(": ")[1]}`;
    return "لا توجد سجلات حضور للطالب في الفترة المختارة";
  })));
  if (item.review) details.append(block("قرار مسجل للمراجع", `${decisionName(item.review.decision)} · ${item.review.note}`));
  $("#review-note").value = "";
}

function decisionName(value) { return ({ verify_data: "التحقق من البيانات", follow_up_approved: "اعتماد خطوة متابعة", no_action: "لا إجراء حاليًا" })[value] || value; }

async function saveReview(event) {
  event.preventDefault();
  const feedback = $("#review-feedback");
  feedback.classList.remove("error");
  try {
    await request("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value, student_id: state.selected, decision: $("#decision-select").value, note: $("#review-note").value }) });
    await loadAnalysis();
    feedback.textContent = "تم حفظ قرار المراجع محليًا. لم يُرسل أي تواصل.";
  } catch (error) { feedback.textContent = error.message; feedback.classList.add("error"); }
}

function addMessage(text, type) {
  const box = node("div", `message ${type}`);
  if (type !== "user") box.append(node("span", "message-label", type === "error" ? "تعذّر الرد" : "مساعد المراجعة"));
  box.append(node("p", "", text));
  $("#chat-messages").append(box);
  box.scrollIntoView({ block: "end", behavior: "smooth" });
  return box;
}

async function sendChat(message) {
  if (state.chatBusy || !message.trim()) return;
  state.chatBusy = true;
  $("#chat-form button").disabled = true;
  addMessage(message.trim(), "user");
  $("#chat-input").value = "";
  const waiting = addMessage("أراجع البيانات الآن…", "assistant");
  try {
    const data = await request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: state.sessionId }) });
    state.sessionId = data.session_id;
    waiting.querySelector("p").textContent = data.answer;
  } catch (error) { waiting.className = "message error"; waiting.querySelector("p").textContent = error.message; }
  finally { state.chatBusy = false; $("#chat-form button").disabled = false; }
}

$("#analyze-btn").addEventListener("click", loadAnalysis);
$("#review-form").addEventListener("submit", saveReview);
$("#chat-form").addEventListener("submit", event => { event.preventDefault(); sendChat($("#chat-input").value); });
$("#chat-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat($("#chat-input").value); } });
$("#clear-chat").addEventListener("click", () => { state.sessionId = null; $("#chat-messages").replaceChildren(); addMessage("محادثة جديدة. اسأل عن سجلات الطلاب أو ابدأ مراجعة تفاعلية.", "assistant"); });
for (const button of document.querySelectorAll("[data-prompt]")) button.addEventListener("click", () => sendChat(button.dataset.prompt));
refreshStatus();
setInterval(refreshStatus, 8000);
loadDatasets().catch(error => { $("#cases-list").replaceChildren(node("p", "empty", error.message)); });
