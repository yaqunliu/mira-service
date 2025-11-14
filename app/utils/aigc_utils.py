# import os
# import json
# import re
# from icode.openai_client import OpenAIClient
# from icode.logger import logger
# from app.core.config import settings


# def gen_playbook_by_chapters(prompt: str, chapter_content: str):
#     client = OpenAIClient(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
#     messages = [
#         {"role": "user", "content": f"{prompt}\n\n下面是章节内容：\n{chapter_content}"}
#     ]
    
#     try:
#         response = client.chat_completion(messages=messages, model=settings.MODEL_NAME)
#         ai_content = response['content']
#         json_match = re.search(r'```json\s*(.*?)\s*```', ai_content, re.DOTALL)
#         if json_match:
#             json_str = json_match.group(1)
#         else:
#             json_str = ai_content
        
#         try:
#             data = json.loads(json_str)
#             return data
                    
#         except json.JSONDecodeError:
#             logger.error(f"Failed to parse JSON: {json_str}")
#             raise json.JSONDecodeError(f"Failed to parse JSON: {json_str}")
            
#     except Exception as e:
#         logger.error(f"Error processing: {e}")
#         raise e