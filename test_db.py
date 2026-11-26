from database import get_connection

connection = get_connection()

with connection.cursor() as cursor:
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()

print("Connected to MySQL successfully!")
print("Tables found:", len(tables))
for row in tables:
    print(" -", list(row.values())[0])

connection.close()