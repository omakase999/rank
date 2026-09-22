const input = document.getElementById('todo-input');
const addBtn = document.getElementById('add-btn');
const list = document.getElementById('todo-list');

function renderTodo(text) {
  const li = document.createElement('li');
  li.textContent = text;
  list.appendChild(li);
}

async function loadTodos() {
  const res = await fetch('/api/todos');
  const todos = await res.json();
  list.innerHTML = '';
  todos.forEach(todo => renderTodo(todo.content));
}

async function addTodo() {
  const text = input.value.trim();
  if (text === '') return;

  await fetch('/api/todos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: text })
  });

  input.value = '';
  loadTodos();
}

addBtn.addEventListener('click', addTodo);

input.addEventListener('keydown', function (e) {
  if (e.key === 'Enter') addTodo();
});

loadTodos();
