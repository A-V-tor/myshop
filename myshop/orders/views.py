from django.contrib import messages
from django.db.models import *
from django.views.generic import ListView

from django.shortcuts import redirect

from orders.models import Cart, Order, StateCart
from product.models import Product
from .other import check_available_stock, get_description_pay, make_task_for_celery


class CartUserView(ListView):
    """Отображение корзины товаров"""

    template_name = 'orders/cart.html'
    model = Cart
    extra_context = {'title': 'Корзина покупок'}
    object_list = None

    def get_queryset(self):
        return Cart.objects.filter(user_id=self.request.user)

    def get_context_data(self, **kwargs):
        context = super(CartUserView, self).get_context_data(**kwargs)
        user = self.request.user

        # сумма текущей корзины
        context['sum'] = (
            Cart.objects.filter(user_id=user)
            .aggregate(sum=Sum('product_id__price'))
            .get('sum')
        )
        return context

    def post(self, request, *args, **kwargs):
        """Oтработка кнопок  удалить товар / оформить заказ"""

        product_id = request.POST.get('remove_product', None)
        make_pay = request.POST.get('order', None)
        # удаление
        if product_id:
            entries = Cart.objects.get(id=int(product_id))
            entries.delete()

        # формирование заказа
        if make_pay:
            status = 'ожидание'
            order_description = [
                (
                    i.product_id.name,
                    i.size,
                    str(i.product_id.price),
                )
                for i in self.get_queryset()
            ]
            order_price = self.get_context_data(**kwargs).get('sum')
            user = self.request.user

            # проверка остатка товара и его списание в случае наличия
            bad_check = check_available_stock(Product, order_description)
            if bad_check:
                messages.add_message(
                    request,
                    messages.ERROR,
                    bad_check,
                )
                return redirect('cart')

            # создание заказа
            order = Order.objects.create(
                status=status,
                products_note=order_description,
                price=order_price,
                user=user,
            )

            # сохранение информации для восстановления остатков при отмене заказа
            state = StateCart.objects.create(
                user=user,
                description=order_description,
                order=order,
            )

            payment = get_description_pay(order)
            url = payment['confirmation']['confirmation_url']
            payment_id = payment['id']

            # создание задачи для проверки оплаты заказа
            make_task_for_celery(order, payment_id, state)

            # очистака корзины
            list_products = self.get_queryset().all()
            list_products.delete()

            # получение ссылки на оплату
            return redirect(url)

        return redirect('cart')


class ProfileUserView(ListView):
    """Отображение личного профиля с заказами"""

    template_name = 'orders/profile.html'
    model = Order
    extra_context = {'title': 'Профиль'}

    def get_queryset(self):
        return Order.objects.filter(user_id=self.request.user).order_by(
            '-date_created', 'status'
        )
