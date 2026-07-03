
# import ast
# import re
# import json

# def extract_json_blocks(text):
#     blocks = re.findall(
#         r'self\.__next_f\.push\(\[\d+,\s*"((?:\\.|[^"])*)"\]\)',
#         text,
#         flags=re.DOTALL,
#     )

#     print("Blocks found:", len(blocks))

#     for i, block in enumerate(blocks):

#         # Convert escaped string to normal string
#         try:
#             block = ast.literal_eval(f'"{block}"')
#         except:
#             continue

#         # Find every JSON object containing "data"
#         for m in re.finditer(r'\{"raw":', block):

#             start = m.start()

#             braces = 0
#             end = None

#             for j in range(start, len(block)):
#                 if block[j] == "{":
#                     braces += 1
#                 elif block[j] == "}":
#                     braces -= 1

#                     if braces == 0:
#                         end = j + 1
#                         break

#             if end:
#                 print("yes")
#                 obj = block[start:end]
#                 data = json.loads(obj)
#                 # raw.pdpDrugData.substituteCatalogData.heroImages

#     return             


# with open("pagesaves/html/ikvaz-500mg-tablet_1000002.html", 'r') as f:
#     text = f.read()

# # extract_json_blocks(text)
# print(extract_json_blocks(text))

import ast
import re
import json

def extract_json_blocks(text):
    # Find all the self.__next_f.push blocks
    blocks = re.findall(
        r'self\.__next_f\.push\(\[\d+,\s*"((?:\\.|[^"])*)"\]\)',
        text,
        flags=re.DOTALL,
    )
    print(f"Blocks found: {len(blocks)}")

    hero_images = None

    for i, block in enumerate(blocks):
        try:
            # Unescape the string
            block = ast.literal_eval(f'"{block}"')
        except:
            continue

        # Look for the heroImages inside raw.pdpDrugData...
        # We'll search for the pattern you mentioned
        match = re.search(r'"heroImages"\s*:\s*(\[.*?\])', block, re.DOTALL)
        if match:
            try:
                hero_images_str = match.group(1)
                # Clean up if needed and parse
                hero_images = json.loads(hero_images_str)
                print(f"✅ Found heroImages in block {i}")
                # Since you want the "last" one, we'll keep updating
            except json.JSONDecodeError:
                continue

    if hero_images:
        print("Hero Images found:")
        print(json.dumps(hero_images, indent=2))
        return hero_images
    else:
        print("No heroImages found")
        return None


# Load the HTML file
with open("pagesaves\html\similac-infant-stage-1-0-to-6-months-formula-jar-powder-400gm_1797250.html", 'r', encoding='utf-8') as f:
    text = f.read()

result = extract_json_blocks(text)
print(result)