import datetime
from decimal import Decimal

from sqlalchemy import Numeric

from app.models import Charge, InsuranceSettlement, Patient, PrepaidTransaction, User


def test_core_financial_columns_use_fixed_point_types():
    assert isinstance(Patient.__table__.c.prepaid_balance.type, Numeric)
    assert Patient.__table__.c.prepaid_balance.type.precision == 12
    assert Patient.__table__.c.prepaid_balance.type.scale == 2
    assert isinstance(Charge.__table__.c.amount.type, Numeric)
    assert isinstance(PrepaidTransaction.__table__.c.amount.type, Numeric)
    assert isinstance(InsuranceSettlement.__table__.c.total_amount.type, Numeric)


def test_money_values_are_stored_to_cents(db_session):
    operator = User(username="money-operator", password="hash", user_role="cashier")
    db_session.add(operator)
    db_session.flush()
    patient = Patient(name="金额精度测试", identity="110101199001019991", prepaid_balance=Decimal("0.30"))
    db_session.add(patient)
    db_session.flush()

    transaction = PrepaidTransaction(
        patient_id=patient.patient_id,
        operator_id=operator.user_id,
        transaction_type="recharge",
        amount=Decimal("0.10"),
        balance_after=Decimal("0.40"),
        create_time=datetime.datetime.now(),
    )
    db_session.add(transaction)
    db_session.commit()
    db_session.refresh(patient)
    db_session.refresh(transaction)

    assert patient.prepaid_balance == Decimal("0.30")
    assert transaction.amount == Decimal("0.10")
    assert transaction.balance_after == Decimal("0.40")
