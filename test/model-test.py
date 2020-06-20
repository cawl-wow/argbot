from datetime import datetime
import models
from models import CharacterRole, CharacterClass, Spec, Character, Team, Raid, Item

print("Hello to the world at " + datetime.now().strftime("%H:%M:%S"))

def init():
  models.Base.metadata.create_all(models.engine)


if __name__ == "__main__":
  print("Initializing Datastore")
  init()

  print("Basic Models" + "\r\n")
  print("Character Roles: ")
  for role in CharacterRole:
    print (role)

  print()
  print("Character Classes: ")
  for cclass in CharacterClass:
    print (cclass)

  print()

  spriest = Spec(character_class=CharacterClass.Priest, name="Shadow", role=CharacterRole.Caster)

  print("Created First Spec: ")
  print(str(spriest))

  print()
  print("Initializing all specs ")
  models.seedSpecs()
  print("Specs seeded!")

  print()
  print("Dumping Specs: ")
  session = models.Session()
  for entry in session.query(Spec).all():
    print(entry)
  print("All Specs dumped from DB!")

  print()
  print("Seeding Characters: ")
  models.seedChars()
  print("Characters Seeded!")

  print()
  print("Dumping Chars: ")
  session = models.Session()
  for entry in session.query(Character).all():
    print(entry)
  print("All Chars dumped from DB!")

  print()
  print("Seeding Teams: ")
  models.seedTeams()
  print("Teams Seeded!")

  print()
  print("Dumping Teams: ")
  session = models.Session()
  for entry in session.query(Team).all():
    print(entry)
  print("Finished dumping Teams")

  print()
  print("Seeding Raids: ")
  models.seedRaids()
  print("Raids seeded!")
  
  print()
  print("Dumping Raids: ")
  session = models.Session()
  for entry in session.query(Raid).all():
    print(entry)
  print("Finished dumping Teams")

  print()
  print("Seeding Items: ")
  models.seedSubclasses() 
  models.seedItems()
  print("Items seeded!")

   
  print()
  print("Dumping Items: ")
  session = models.Session()
  for entry in session.query(Item).all():
    print(entry)
  print("Finished dumping Items")

  
  print("Ending run!")
