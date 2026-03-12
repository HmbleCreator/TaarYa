from src.agent.agent import ask

history = [
    {'role': 'human', 'content': 'Show me stars near RA=45, Dec=0'},
    {'role': 'ai', 'content': 'I found 20 stars within 1 degree. The brightest is Source ID 3332894779520.'}
]
result = ask('which is the brightest star in the above detected stars?', history)
print(result['answer'])
