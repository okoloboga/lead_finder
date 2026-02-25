from aiogram.fsm.state import State, StatesGroup


class ProgramCreate(StatesGroup):
    enter_name = State()
    enter_niche_description = State()
    enter_chats = State()
    confirm_settings = State()

class Auth(StatesGroup):
    enter_code = State()
    enter_password = State()


class ProgramEdit(StatesGroup):
    edit_name = State()
    edit_niche = State()
    edit_chats = State()
    edit_settings = State()


class UserProfile(StatesGroup):
    enter_services_description = State()


class AdminPanel(StatesGroup):
    waiting_user_query = State()
