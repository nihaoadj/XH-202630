(() => {
  'use strict'

  const CHANNEL = 'html-practice'
  const VERSION = 1
  const root = document.querySelector('.html-practice-root')
  if (!root) return

  function send(type, payload = {}) {
    window.parent.postMessage({ channel: CHANNEL, version: VERSION, type, payload }, '*')
  }

  let heightFrame = 0
  function reportHeight() {
    cancelAnimationFrame(heightFrame)
    heightFrame = requestAnimationFrame(() => {
      const height = Math.ceil(root.getBoundingClientRect().height + 24)
      send('height', { height })
    })
  }

  const steps = Array.from(root.querySelectorAll('[data-practice-step]'))
  const completedSteps = new Set()

  function renderSteps() {
    steps.forEach((step, index) => {
      const unlocked = index === 0 || completedSteps.has(index - 1)
      const complete = completedSteps.has(index)
      step.classList.toggle('practice-step-locked', !unlocked)
      step.classList.toggle('practice-step-complete', complete)
      step.setAttribute('aria-disabled', String(!unlocked))
      const button = step.querySelector(':scope > .practice-complete-button')
      if (button) {
        button.disabled = !unlocked
        button.textContent = complete ? '已完成此步' : '完成并继续'
      }
    })
    send('progress', { completed: completedSteps.size, total: steps.length })
    reportHeight()
  }

  steps.forEach((step, index) => {
    let button = step.querySelector(':scope > [data-practice-complete]')
    if (!button) {
      button = document.createElement('button')
      button.type = 'button'
      button.dataset.practiceComplete = 'true'
      button.className = 'practice-complete-button'
      step.append(button)
    } else {
      button.classList.add('practice-complete-button')
    }
    button.addEventListener('click', () => {
      if (index > 0 && !completedSteps.has(index - 1)) return
      if (completedSteps.has(index)) completedSteps.delete(index)
      else completedSteps.add(index)
      // Relocking a step also clears completion of its dependent successors.
      if (!completedSteps.has(index)) {
        for (let next = index + 1; next < steps.length; next += 1) completedSteps.delete(next)
      }
      renderSteps()
    })
  })

  root.querySelectorAll('[data-practice-checklist]').forEach((checklist) => {
    const inputs = Array.from(checklist.querySelectorAll('input[type="checkbox"]'))
    const progress = document.createElement('div')
    progress.className = 'practice-checklist-progress'
    checklist.append(progress)
    const update = () => {
      const checked = inputs.filter((item) => item.checked).length
      progress.textContent = `已完成 ${checked}/${inputs.length}`
      send('checklist-progress', {
        checklistId: checklist.dataset.sourceChecklistId || checklist.dataset.practiceChecklist || '',
        checked,
        total: inputs.length,
      })
      reportHeight()
    }
    inputs.forEach((input) => input.addEventListener('change', update))
    update()
  })

  function inputIsCorrect(input, quiz) {
    if (input.dataset.correct != null) return input.dataset.correct === 'true'
    const option = input.closest('[data-correct]')
    if (option) return option.dataset.correct === 'true'
    const answer = quiz.dataset.correctAnswer || quiz.dataset.answer
    return answer != null && String(input.value) === String(answer)
  }

  root.querySelectorAll('[data-practice-quiz]').forEach((quiz) => {
    const inputs = Array.from(quiz.querySelectorAll('input[type="radio"], input[type="checkbox"]'))
    let submit = quiz.querySelector('[data-practice-quiz-submit]')
    if (!submit) {
      submit = document.createElement('button')
      submit.type = 'button'
      submit.dataset.practiceQuizSubmit = 'true'
      submit.textContent = '检查答案'
      quiz.append(submit)
    }
    submit.classList.add('practice-quiz-submit')
    let feedback = quiz.querySelector('[data-practice-feedback]')
    if (!feedback) {
      feedback = document.createElement('div')
      feedback.dataset.practiceFeedback = 'true'
      quiz.append(feedback)
    }
    feedback.classList.add('practice-quiz-feedback')

    submit.addEventListener('click', () => {
      const selected = inputs.filter((input) => input.checked)
      const hasAnswerKey = inputs.some((input) => (
        input.dataset.correct != null
          || input.closest('[data-correct]')
          || quiz.dataset.correctAnswer != null
          || quiz.dataset.answer != null
      ))
      const correct = hasAnswerKey
        && selected.length > 0
        && selected.every((input) => inputIsCorrect(input, quiz))
        && inputs.filter((input) => inputIsCorrect(input, quiz)).every((input) => input.checked)
      feedback.classList.toggle('is-correct', correct)
      feedback.classList.toggle('is-incorrect', hasAnswerKey && !correct)
      feedback.textContent = !selected.length
        ? '请先选择答案。'
        : !hasAnswerKey
          ? '作答已记录，请对照指南解析复盘。'
          : correct ? '回答正确。' : '暂未通过，可回看上方步骤后重试。'
      send('quiz-result', {
        quizId: quiz.dataset.sourceQuizId || quiz.dataset.practiceQuiz || '',
        correct: hasAnswerKey ? correct : null,
      })
      reportHeight()
    })
  })

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return
    }
    const field = document.createElement('textarea')
    field.value = text
    field.setAttribute('readonly', '')
    field.style.position = 'fixed'
    field.style.opacity = '0'
    document.body.append(field)
    field.select()
    document.execCommand('copy')
    field.remove()
  }

  root.querySelectorAll('pre > code').forEach((code) => {
    const pre = code.parentElement
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'practice-copy-button'
    button.textContent = '复制代码'
    button.addEventListener('click', async () => {
      try {
        await copyText(code.textContent || '')
        button.textContent = '已复制'
      } catch {
        button.textContent = '复制失败'
      }
      setTimeout(() => { button.textContent = '复制代码' }, 1600)
    })
    pre.append(button)
  })

  if (typeof ResizeObserver === 'function') new ResizeObserver(reportHeight).observe(root)
  renderSteps()
  send('ready', { runtimeVersion: VERSION })
  reportHeight()
})()
