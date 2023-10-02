from peewee import *
import datetime

database = SqliteDatabase(None)

class BaseModel(Model):
    class Meta:
        database = database

class Student(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField()
    sid = IntegerField(unique=True)
    created_date = DateTimeField(default=datetime.datetime.now)

class Lecture(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField()
    division = IntegerField()
    created_date = DateTimeField(default=datetime.datetime.now)
    #is_published = BooleanField(default=True)

class Enrollment(BaseModel):
    id = IntegerField(primary_key=True)
    student = ForeignKeyField(Student)
    lecture = ForeignKeyField(Lecture)
    gitaddr = CharField()

#db.create_tables([Student, Lecture, Enrollment])

# lecture = Lecture(name='python', division=1)
# lecture.save()

# stu = Student(name='전미소', sid=12121212)
# stu.save()
#
# students = Student.select()
# for s in students:
#     en = Enrollment(student=s, lecture=lec[0], gitaddr='')
#     en.save()


# charlie = User.create(username='charlie')
# huey = User(username='huey')
# huey.save()
#
# # No need to set `is_published` or `created_date` since they
# # will just use the default values we specified.
# Tweet.create(user=charlie, message='My first tweet')