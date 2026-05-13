from flask import Flask, jsonify, request
app = Flask(__name__)
todos = []
@app.route('/todos', methods=['GET'])
def list_todos():
    return jsonify(todos)
@app.route('/todos', methods=['POST'])
def add_todo():
    todos.append(request.get_json(force=True, silent=True) or {})
    return jsonify({'ok': True})
if __name__ == '__main__':
    app.run(port=5001, debug=False)