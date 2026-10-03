const $ = (selector) => document.querySelector(selector);
const state = { dataset: null, report: null, selected: null, sessionId: null, chatBusy: false,
  guided: false, question: null, freeformAnswerTo: null, freeformSave: false,
  actionBusy: false, actionKey: null, actionRequestId: null };

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
  const missing = summary.missing_attendance || [];
  $("#missing-count").textContent = `${missing.length} سجل`;
  const missingList = $("#missing-list");
  missingList.replaceChildren();
  if (!missing.length) missingList.append(node("p", "empty", "كل أيام الدوام المعروفة لها حالة مسجلة لكل طالب في هذه الفترة."));
  for (const item of missing) {
    missingList.append(node("div", "missing-row", `${item.alias} · ${item.student_id} · ${item.date} · ${item.reason === "unrecorded" ? "غير مسجل" : "سجل مفقود"}`));
  }
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
  $("#feedback-student").value = item.student_id;
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
  const params = new URLSearchParams({ data_file: state.dataset, student_id: item.student_id });
  request(`/api/context?${params}`).then(data => {
    if (state.selected !== item.student_id || !data.events.length) return;
    details.append(block("سياق محفوظ من الجولات السابقة", data.events.slice(0, 5).map(entry => {
      if (entry.type === "feedback") return `${entry.at.slice(0, 10)} · تقييم: ${entry.label} · ${entry.note}`;
      if (entry.type === "review") return `${entry.at.slice(0, 10)} · قرار مراجعة: ${decisionName(entry.decision)} · ${entry.note}`;
      if (entry.type === "answer") return `${entry.at.slice(0, 10)} · إجابة: ${entry.answer}`;
      return `${entry.at.slice(0, 10)} · ${entry.action}: ${entry.state}`;
    })));
  }).catch(() => {});
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

function renderQuestion(box, question) {
  if (!question || !Array.isArray(question.options)) return;
  const panel = node("div", "question-panel");
  panel.append(node("strong", "", question.text));
  for (const option of question.options) {
    const button = node("button", "question-option", option);
    button.type = "button";
    button.addEventListener("click", () => {
      if (option === "تفصيل آخر" || option.includes("اكتب النتيجة")) {
        state.freeformAnswerTo = question.id;
        state.freeformSave = option.includes("اكتب النتيجة");
        $("#chat-input").placeholder = state.freeformSave ? "اكتب نتيجة المتابعة لتحفظها…" : "اكتب التفاصيل التي تعرفها عن السؤال…";
        $("#chat-input").focus();
      } else sendChat(option, question.id);
    });
    panel.append(button);
  }
  box.append(panel);
}

async function sendChat(message, answerTo = state.freeformAnswerTo, saveAnswer = state.freeformSave) {
  if (state.chatBusy || !message.trim()) return;
  state.chatBusy = true;
  $("#chat-form button").disabled = true;
  const oldQuestion = state.question;
  state.question = null;
  state.freeformAnswerTo = null;
  state.freeformSave = false;
  addMessage(message.trim(), "user");
  $("#chat-input").value = "";
  const waiting = addMessage("أراجع البيانات الآن…", "assistant");
  try {
    const data = await request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: state.sessionId, guided: state.guided, data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value, answer_to: answerTo, save_answer: saveAnswer }) });
    state.sessionId = data.session_id;
    waiting.querySelector("p").textContent = data.answer;
    state.question = data.question;
    renderQuestion(waiting, data.question);
    if (data.changed) await loadAnalysis();
  } catch (error) { state.question = oldQuestion; state.freeformAnswerTo = answerTo; state.freeformSave = saveAnswer; waiting.className = "message error"; waiting.querySelector("p").textContent = error.message; }
  finally { state.chatBusy = false; $("#chat-form button").disabled = false; }
}

async function saveFeedback(event) {
  event.preventDefault();
  const result = $("#feedback-result");
  result.classList.remove("error");
  try {
    const data = await request("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value, student_id: $("#feedback-student").value.trim(), label: $("#feedback-label").value, note: $("#feedback-note").value }) });
    result.textContent = data.policy_changed ? `حُفظ التقييم وتحدّثت قواعد الفرز تلقائيًا إلى النسخة ${data.policy.version}.` : "حُفظ التقييم. سيُراجع الوكيل القواعد تلقائيًا عندما تتوفر أمثلة كافية.";
    $("#feedback-note").value = "";
    if (data.policy_changed) await loadAnalysis();
  } catch (error) { result.textContent = error.message; result.classList.add("error"); }
}

async function createReport(event) {
  event.preventDefault();
  const feedback = $("#report-result");
  feedback.classList.remove("error");
  try {
    const data = await request("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value, purpose: $("#report-purpose").value }) });
    const item = data.report;
    feedback.textContent = `أُنشئ التقرير لغرض: ${item.purpose}`;
    const box = $("#report-body");
    box.replaceChildren(block("الحضور حسب اليوم", item.attendance_by_date.map(day => `${day.date}: ${day.present} حاضر، ${day.absent} غائب، ${day.unrecorded + day.missing_record} دون حضور/غياب محسوم`)));
    box.append(block("الحالات والبيانات الناقصة", `${item.cases.length} حالات للمراجعة، ${item.missing_attendance.length} سجلات حضور تحتاج استكمالًا.`));
  } catch (error) { feedback.textContent = error.message; feedback.classList.add("error"); }
}

function showActionFields() {
  const kind = $("#action-type").value;
  $("#action-day-fields").hidden = !["record_attendance", "add_school_day"].includes(kind);
  $("#action-followup-fields").hidden = kind !== "resolve_followup";
  $("#action-contact-fields").hidden = !["queue_contact", "send_email"].includes(kind);
  $("#action-status").parentElement.hidden = kind !== "record_attendance";
}

async function runAction(event) {
  event.preventDefault();
  if (state.actionBusy) return;
  const feedback = $("#action-result");
  feedback.classList.remove("error");
  const action = $("#action-type").value;
  const button = $("#action-form button[type=submit]");
  try {
    if (action !== "add_school_day" && !state.selected) throw new Error("اختر الطالب من قائمة الحالات أولًا");
    const body = { data_file: state.dataset, actor: $("#action-actor").value, action,
      student_id: state.selected, day: $("#action-day").value, status: $("#action-status").value,
      followup_id: $("#action-followup-id").value, outcome: $("#action-outcome").value,
      recipient_type: $("#action-recipient").value, subject: $("#action-subject").value,
      message: $("#action-message").value };
    const key = JSON.stringify(body);
    if (state.actionKey !== key) { state.actionKey = key; state.actionRequestId = crypto.randomUUID(); }
    body.request_id = state.actionRequestId;
    state.actionBusy = true;
    button.disabled = true;
    const data = await request("/api/actions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    feedback.textContent = data.action.state === "sent" ? "أكّد خادم البريد إرسال الرسالة وسُجّل الإجراء." : data.action.state === "queued_local" ? "حُفظ طلب التواصل محليًا، ولم تُرسل رسالة." : ["failed_or_unknown", "sending"].includes(data.action.state) ? "لم يُؤكَّد الإرسال. راجع مزود البريد قبل طلب جديد." : "نُفّذ التعديل على النسخة المحلية وسُجّل في سجل الإجراءات.";
    state.actionKey = null;
    state.actionRequestId = null;
    if (["record_attendance", "resolve_followup", "add_school_day"].includes(action)) await loadAnalysis();
  } catch (error) { feedback.textContent = error.message; feedback.classList.add("error"); }
  finally { state.actionBusy = false; button.disabled = false; }
}

$("#analyze-btn").addEventListener("click", loadAnalysis);
$("#review-form").addEventListener("submit", saveReview);
$("#feedback-form").addEventListener("submit", saveFeedback);
$("#report-form").addEventListener("submit", createReport);
$("#action-form").addEventListener("submit", runAction);
$("#action-type").addEventListener("change", showActionFields);
showActionFields();
$("#chat-form").addEventListener("submit", event => { event.preventDefault(); sendChat($("#chat-input").value); });
$("#chat-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat($("#chat-input").value); } });
$("#clear-chat").addEventListener("click", () => { state.sessionId = null; state.guided = false; state.question = null; state.freeformAnswerTo = null; state.freeformSave = false; $("#chat-messages").replaceChildren(); addMessage("محادثة جديدة. اسأل عن سجلات الطلاب أو ابدأ مراجعة تفاعلية.", "assistant"); });
$("#guided-start").addEventListener("click", () => { state.sessionId = null; state.guided = true; state.question = null; state.freeformAnswerTo = null; state.freeformSave = false; $("#chat-messages").replaceChildren(); sendChat("ابدأ مراجعة تفاعلية للملف والفترة المحددين."); });
for (const button of document.querySelectorAll("[data-prompt]")) button.addEventListener("click", () => sendChat(button.dataset.prompt));
refreshStatus();
setInterval(refreshStatus, 8000);
loadDatasets().catch(error => { $("#cases-list").replaceChildren(node("p", "empty", error.message)); });
