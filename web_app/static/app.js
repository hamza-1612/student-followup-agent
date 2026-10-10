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
    row.setAttribute("aria-label", `عرض سجل ${item.alias}`);
    row.addEventListener("click", () => openStudentRecord(item));
    list.append(row);
  }
}

function priorityClass(item) { return item.priority === "high" ? "high" : item.priority === "standard" ? "standard" : "neutral"; }
function priorityName(item) { return item.priority === "high" ? "أولوية عالية" : item.priority === "standard" ? "أولوية عادية" : "تحتاج تحققًا"; }
function subjectName(value) { return ({ Mathematics: "الرياضيات", Arabic: "اللغة العربية", English: "اللغة الإنجليزية" })[value] || value; }
function alertName(item) { return item.type === "score_drop" ? `تراجع في ${subjectName(item.subject)}` : "غياب مسجل"; }

function recordSection(title, rows, emptyText) {
  const section = node("section", "record-section");
  section.append(node("h3", "", title));
  if (rows.length) section.append(...rows);
  else section.append(node("p", "record-empty", emptyText));
  return section;
}

function recordDate(value) {
  const time = node("time", "record-date", value);
  time.dateTime = value;
  return time;
}

function renderStudentRecord(record) {
  $("#record-title").textContent = record.name;
  $("#record-period").textContent = `الحضور من ${record.period.start} إلى ${record.period.end}`;
  const content = $("#record-content");
  content.replaceChildren();

  if (record.alerts.length) {
    const signals = node("div", "record-signals");
    signals.append(node("strong", "", "مؤشرات تستحق المراجعة"));
    for (const item of record.alerts) {
      const detail = item.type === "score_drop"
        ? `تراجع ${subjectName(item.subject)} من ${item.previous.percent}% إلى ${item.current.percent}%`
        : `${item.count} غياب مسجل: ${item.dates.join("، ")}`;
      signals.append(node("p", "", detail));
    }
    content.append(signals);
  }

  const statusName = { present: "حاضر", absent: "غائب", unrecorded: "غير مسجل", missing_row: "لا يوجد سجل" };
  const counts = { present: 0, absent: 0, unrecorded: 0, missing_row: 0 };
  for (const day of record.attendance) counts[day.status]++;
  const attendance = node("div", "record-attendance");
  attendance.append(node("p", "record-counts", `${counts.present} حاضر · ${counts.absent} غائب · ${counts.unrecorded} غير مسجل · ${counts.missing_row} بلا سجل`));
  const days = node("div", "record-days");
  for (const day of record.attendance) {
    const cell = node("div", `record-day status-${day.status}`);
    cell.append(recordDate(day.date), node("strong", "", statusName[day.status]));
    days.append(cell);
  }
  if (record.attendance.length) attendance.append(days);
  content.append(recordSection("الحضور خلال الفترة", record.attendance.length ? [attendance] : [], "لا توجد أيام دوام مسجلة في هذه الفترة."));

  const assessments = record.assessments.map(item => {
    const row = node("div", "record-line");
    const detail = node("div", "record-line-copy");
    detail.append(node("strong", "", subjectName(item.subject)), node("span", "", `${item.score} من ${item.max_score} (${item.percent}%)`));
    row.append(detail, recordDate(item.date));
    return row;
  });
  content.append(recordSection("التقييمات المسجلة حتى نهاية الفترة", assessments, "لا توجد تقييمات مسجلة."));

  const followups = record.followups.map(item => {
    const row = node("div", "record-line");
    const detail = node("div", "record-line-copy");
    detail.append(node("strong", "", item.topic), node("span", "", item.outcome));
    row.append(detail, recordDate(item.date));
    return row;
  });
  content.append(recordSection("المتابعات السابقة", followups, "لا توجد متابعات سابقة مسجلة."));

  const actionName = { record_attendance: "تعديل حضور", resolve_followup: "تحديث متابعة",
    send_demo: "رسالة مسجلة", send_email: "بريد إلكتروني", queue_contact: "طلب تواصل", add_school_day: "إضافة يوم دوام" };
  const actions = record.actions.map(item => {
    const row = node("div", "record-line");
    const detail = node("div", "record-line-copy");
    const info = item.details || {};
    const description = item.action === "record_attendance" ? `${info.day}: ${statusName[info.after] || info.after}`
      : item.action === "resolve_followup" ? info.after
      : item.action === "send_demo" ? info.message
      : item.action === "send_email" ? `${item.state === "sent" ? "أُرسل" : "لم يتأكد الإرسال"}: ${info.subject || ""}`
      : info.subject || info.day || "";
    detail.append(node("strong", "", actionName[item.action] || item.action), node("span", "", description));
    row.append(detail, recordDate(item.at.slice(0, 10)));
    return row;
  });
  content.append(recordSection("الإجراءات المحلية", actions, "لا توجد إجراءات مسجلة لهذا الطالب."));
}

async function openStudentRecord(item) {
  const dialog = $("#student-record");
  const requestId = state.recordRequest = (state.recordRequest || 0) + 1;
  $("#record-title").textContent = item.alias;
  $("#record-period").textContent = "";
  $("#record-content").replaceChildren(node("p", "record-empty", "جارٍ تحميل سجل الطالب…"));
  dialog.showModal();
  try {
    const params = new URLSearchParams({ data_file: state.dataset, student_id: item.student_id,
      start: $("#period-start").value, end: $("#period-end").value });
    const data = await request(`/api/student-record?${params}`);
    if (dialog.open && requestId === state.recordRequest) renderStudentRecord(data.record);
  } catch (error) {
    if (dialog.open && requestId === state.recordRequest) {
      $("#record-content").replaceChildren(node("p", "record-empty", `تعذّر تحميل السجل: ${error.message}`));
    }
  }
}
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

function renderChoiceCard(question) {
  clearQuestion();
  if (!question || !Array.isArray(question.options) || !question.options.length) return;
  const panel = $("#composer-question");
  panel.hidden = false;
  const card = { panel, closed: false, selected: null, question };
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
        sendChat(option, question.id);
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
  sendChat(message, isAnswer ? card.question.id : null, saveAnswer);
}

function resetChat() {
  if (state.chatBusy) return;
  state.sessionId = null;
  state.guided = false;
  clearQuestion();
  $("#chat-messages").replaceChildren();
  $("#chat-input").value = "";
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
    if (data.reset_chat) {
      $("#chat-messages").replaceChildren();
      addMessage(data.answer, "assistant");
    } else {
      waiting.querySelector("p").textContent = data.answer;
    }
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
$("#clear-chat").addEventListener("click", resetChat);
$("#close-record").addEventListener("click", () => $("#student-record").close());
$("#student-record").addEventListener("close", () => { state.recordRequest = (state.recordRequest || 0) + 1; });
resetChat();
refreshStatus();
setInterval(refreshStatus, 8000);
setInterval(refreshDataRevision, 8000);
loadDatasets().catch(error => { $("#cases-list").replaceChildren(node("p", "empty", error.message)); });
