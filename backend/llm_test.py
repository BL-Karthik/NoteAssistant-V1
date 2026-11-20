
# from service.llm_service import analyze_message


# tests = [
#     {
#         "name": "TEST 1 - Continue existing topic",
#         "messages": [
#             {"role": "user", "content": "I'm building a Note Assistant using FastAPI."},
#             {"role": "assistant", "content": "What database are you using?"},
#             {"role": "user", "content": "I'm using PostgreSQL for conversation history."}
#         ]
#     },
#     {
#         "name": "TEST 2 - Introduce a new topic",
#         "messages": [
#             {"role": "user", "content": "I'm building a Note Assistant using FastAPI."},
#             {"role": "assistant", "content": "What database are you using?"},
#             {"role": "user", "content": "I'm using PostgreSQL for conversation history."},
#             {"role": "assistant", "content": "That makes sense."},
#             {"role": "user", "content": "I want to learn Java microservices."}
#         ]
#     },
#     {
#         "name": "TEST 3 - Return to an older topic",
#         "messages": [
#             {"role": "user", "content": "I'm building a Note Assistant using FastAPI."},
#             {"role": "assistant", "content": "What database are you using?"},
#             {"role": "user", "content": "I'm using PostgreSQL for conversation history."},
#             {"role": "assistant", "content": "That makes sense."},
#             {"role": "user", "content": "I want to learn Java microservices."},
#             {"role": "assistant", "content": "Great! What would you like to learn?"},
#             {"role": "user", "content": "Let's continue our Note Assistant project."}
#         ]
#     }
# ]


# for test in tests:
#     print(f"\n========== {test['name']} ==========\n")

#     try:
#         result = analyze_message(test["messages"])

#         print("Topic:", result["topic_name"])
#         print("Action:", result["topic_action"])
#         print("Intent:", result["intent"])

#     except Exception as error:
#         print("ERROR:", error)

#     print("\n====================================")
