const $ = (selector) => document.querySelector(selector);
const state = { dataset: null, report: null, sessionId: null, chatBusy: false,
  guided: false, question: null, activeQuestionCard: null,
  dataRevision: null, analysisBusy: false, revisionBusy: false };

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

async function refreshDataRevision() {
  if (!state.dataset || state.dataRevision === null || state.chatBusy || state.analysisBusy || state.revisionBusy) return;
  state.revisionBusy = true;
  try {
    const data = await request(`/api/revision?${new URLSearchParams({ data_file: state.dataset })}`);
    if (data.revision !== state.dataRevision) await loadAnalysis();
  } catch { /* A temporary connection issue must not replace the displayed report. */ }
  finally { state.revisionBusy = false; }
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
    const option = node("option", "", `بيانات الطلاب · ${item.students} طالبًا`);
    option.value = item.data_file;
    select.append(option);
  }
  if (!data.datasets.length) throw new Error("لا توجد ملفات JSON داخل مجلد data");
  state.dataset = data.datasets[0].data_file;
  select.value = state.dataset;
  applyDatasetDates(data.datasets[0]);
  select.addEventListener("change", async () => {
    const item = data.datasets.find((entry) => entry.data_file === select.value);
    state.dataset = item.data_file;
    applyDatasetDates(item);
    await loadAnalysis();
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
  state.analysisBusy = true;
  button.disabled = true;
  button.textContent = "جارٍ الفحص…";
  try {
    const params = new URLSearchParams({ data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value });
    state.report = await request(`/api/analysis?${params}`);
    state.dataRevision = state.report.revision;
    renderReport();
  } catch (error) {
    $("#cases-list").replaceChildren(node("p", "empty", error.message));
    $("#attendance-chart").replaceChildren(node("p", "empty", "تعذّر عرض الحضور للفترة المختارة."));
  } finally {
    state.analysisBusy = false;
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
    row.append(node("span", "case-initial", item.alias.trim().slice(0, 1)));
    const copy = node("span", "case-copy");
    copy.append(node("strong", "", item.alias));
    copy.append(node("span", "", item.alerts.length ? item.alerts.map(alertName).join(" · ") : "سجل حضور يحتاج تحققًا"));
    row.append(copy, node("span", `priority-tag ${priorityClass(item)}`, priorityName(item)));
    row.addEventListener("click", () => sendChat(`ما حالة ${item.alias} وما الخطوة المناسبة؟`));
    list.append(row);
  }
}

function priorityClass(item) { return item.priority === "high" ? "high" : item.priority === "standard" ? "standard" : "neutral"; }
function priorityName(item) { return item.priority === "high" ? "أولوية عالية" : item.priority === "standard" ? "أولوية عادية" : "تحتاج تحققًا"; }
function subjectName(value) { return ({ Mathematics: "الرياضيات", Arabic: "اللغة العربية", English: "اللغة الإنجليزية" })[value] || value; }
function alertName(item) { return item.type === "score_drop" ? `تراجع في ${subjectName(item.subject)}` : "غياب مسجل"; }
function scrollChatToBottom() {
  const messages = $("#chat-messages");
  messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
}

function addMessage(text, type) {
  const box = node("div", `message ${type}`);
  if (type !== "user") box.append(node("span", "message-label", type === "error" ? "تعذّر الرد" : "مساعد المراجعة"));
  box.append(node("p", "", text));
  $("#chat-messages").append(box);
  scrollChatToBottom();
  return box;
}


function customChoice(option) {
  return option === "تفصيل آخر" || option.includes("اكتب النتيجة") || option === "تعديل الرسالة";
}

function disableQuestionCard(card, disabled) {
  card.panel.querySelectorAll("button, input").forEach(control => {
    control.disabled = disabled || card.closed;
  });
}

function clearQuestion() {
  state.activeQuestionCard = null;
  state.question = null;
  const panel = $("#composer-question");
  panel.replaceChildren();
  panel.hidden = true;
  $("#chat-input").placeholder = "اسأل عن طالب أو حالة…";
  $("#chat-input").maxLength = 4000;
}

function renderChoiceCard(question, starter = false) {
  clearQuestion();
  if (!question || !Array.isArray(question.options) || !question.options.length) return;
  const panel = $("#composer-question");
  panel.hidden = false;
  const card = { panel, closed: false, selected: null, starter, question };
  const heading = node("div", "question-heading");
  heading.append(node("strong", "", question.text));
  const close = node("button", "question-close", "×");
  close.type = "button";
  close.title = "إخفاء الخيارات";
  close.setAttribute("aria-label", "إخفاء الخيارات");
  close.addEventListener("click", () => {
    if (state.chatBusy) return;
    clearQuestion();
  });
  heading.append(close);
  panel.append(heading);

  const choices = node("div", "question-choices");
  choices.setAttribute("role", "group");
  choices.setAttribute("aria-label", question.text);
  for (const option of question.options) {
    const button = node("button", "question-option");
    button.type = "button";
    button.append(node("span", "question-choice-text", option));
    button.addEventListener("click", () => {
      if (state.chatBusy) return;
      if (!customChoice(option)) {
        sendChat(option, starter ? null : question.id);
        return;
      }
      card.selected = option;
      const input = $("#chat-input");
      input.maxLength = question.id?.startsWith("send:") ? 2000 : 4000;
      if (option === "تعديل الرسالة") {
        input.placeholder = "اكتب الرسالة المعدّلة…";
        input.value = question.draft || "";
      } else if (option.includes("اكتب النتيجة")) {
        input.placeholder = "اكتب نتيجة المتابعة…";
        input.value = "";
      } else {
        input.placeholder = "اكتب التفاصيل التي تعرفها…";
        input.value = "";
      }
      input.focus();
    });
    choices.append(button);
  }
  panel.append(choices);
  state.activeQuestionCard = card;
}

function submitComposer() {
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) { input.focus(); return; }
  const card = state.activeQuestionCard;
  const selected = card?.selected;
  const isAnswer = Boolean(selected && customChoice(selected));
  const saveAnswer = isAnswer &&
    (selected.includes("اكتب النتيجة") || selected === "تعديل الرسالة" ||
      (selected === "تفصيل آخر" && card.question.id?.startsWith("model:")));
  sendChat(message, isAnswer && !card.starter ? card.question.id : null, saveAnswer);
}

function showWelcome() {
  clearQuestion();
  $("#chat-messages").replaceChildren();
  addMessage("اسأل عن طالب أو اختر حالة من القائمة، وسأعرض لك ما نعرفه والخطوة المناسبة.", "assistant");
  renderChoiceCard({
    text: "شو بتحب نراجع أولًا؟",
    options: ["راجع الحالات في الفترة المحددة", "ما حالة تالا أمجد؟", "اعرض سجلات الحضور غير المسجلة"]
  }, true);
}


async function sendChat(message, answerTo = null, saveAnswer = false) {
  if (state.chatBusy || !message.trim()) return;
  state.chatBusy = true;
  $(".composer-input button").disabled = true;
  const previousCard = state.activeQuestionCard;
  if (previousCard) disableQuestionCard(previousCard, true);
  addMessage(message.trim(), "user");
  $("#chat-input").value = "";
  const waiting = addMessage("أراجع البيانات الآن…", "assistant");
  try {
    const data = await request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, session_id: state.sessionId, guided: state.guided, data_file: state.dataset, start: $("#period-start").value, end: $("#period-end").value, answer_to: answerTo, save_answer: saveAnswer }) });
    state.sessionId = data.session_id;
    waiting.querySelector("p").textContent = data.answer;
    clearQuestion();
    state.question = data.question;
    renderChoiceCard(data.question);
    scrollChatToBottom();
    if (data.changed) await loadAnalysis();
  } catch (error) {
    if (previousCard) disableQuestionCard(previousCard, false);
    waiting.className = "message error";
    waiting.querySelector("p").textContent = error.message;
  } finally {
    state.chatBusy = false;
    $(".composer-input button").disabled = false;
  }
}

$("#analyze-btn").addEventListener("click", () => loadAnalysis());
$("#chat-form").addEventListener("submit", event => { event.preventDefault(); submitComposer(); });
$("#chat-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitComposer(); } });
$("#clear-chat").addEventListener("click", () => { state.sessionId = null; state.guided = false; state.question = null; showWelcome(); });
showWelcome();
refreshStatus();
setInterval(refreshStatus, 8000);
setInterval(refreshDataRevision, 8000);
loadDatasets().catch(error => { $("#cases-list").replaceChildren(node("p", "empty", error.message)); });
