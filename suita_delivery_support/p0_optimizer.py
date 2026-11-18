"""P0の入力検証エラーを共通化するモジュール。

以前の単一品目の簡略モデルは必要な制約を欠くため廃止し、
現在はp0_full_constraints.pyを用いる。"""
class P0InputError(ValueError):
    pass
