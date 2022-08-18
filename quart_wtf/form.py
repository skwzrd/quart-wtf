"""
Quart-WTF Form
"""
from __future__ import annotations
import asyncio
from typing import Optional, Union
from markupsafe import Markup
from quart import request
from wtforms import Form, Label, ValidationError
from wtforms.widgets import HiddenInput
from werkzeug.datastructures import MultiDict, CombinedMultiDict, ImmutableMultiDict
from .meta import QuartFormMeta

SUBMIT_METHODS = ("POST", "PUT", "PATCH", "DELETE")

_Auto = object()

class QuartForm(Form):
    """
    Quart specific subclass of WTForms :class:`~wtforms.form.Form`.
    To populate from submitted formdata use the ```.from_submit()``` class
    method to initialize the instance.
    """
    Labels: Optional[dict] = None

    Meta = QuartFormMeta

    def __init__(
        self,
        formdata: Optional[Union[MultiDict, CombinedMultiDict, ImmutableMultiDict]]=None,
        obj=None,
        prefix='',
        data: Optional[dict]=None,
        meta: Optional[dict]=None,
        labels: Optional[dict]=None,
        **kwargs
        ) -> None:
        """
        Initialize the form. Takes all the same parameters as WTForms
        base form.
        """
        # Set the labels for the field if they have been passed.
        if labels is not None:
            for field, text in labels:
                self[field].label = Label(self[field].id, text)

        super().__init__(formdata, obj, prefix, data, meta, **kwargs)

    @classmethod
    async def create_form(
        cls,
        formdata: Union[object, MultiDict, CombinedMultiDict, ImmutableMultiDict]=_Auto,
        obj=None,
        prefix: Optional[str]=None,
        data: Optional[dict]=None,
        meta: Optional[dict]=None,
        labels: Optional[dict]=None,
        **kwargs
        ) -> QuartForm:
        """
        This is a async method will create a new instance of ``QuartForm``.

        This method is primiarly used to intialize the class from submitted
        formdata from ``Quart.request``. If a request is a POST, PUT, PATCH,
        or DELETE method. The form will be intialized using the request. Otherwise
        it will initialized using the defaults. This is required since ``request.files``,
        ``request.form``, and ``request.json`` are coroutines and need to be called in an
        async manner.

        Also, if you are using ``quart_babel`` for translating components of this form, such
        as field labels. This method will call the lazy text as a coroutine, since ``quart_babel``
        use a coroutine to get the locale of of the user.

        """
        # check if formdata needs to be obtained from the request.
        if formdata is _Auto:
            if cls.is_submitted():
                formdata = await cls._get_formdata()
            else:
                formdata = None

        # check if the `Labels` dict has any data and run. This will also check the `labels`
        # dict that is passed to this classmethod.
        if (cls.Labels or labels) is not None:
            translated_labels = {}

            async def translate_labels(label_data: dict) -> None:
                for field, text in label_data:
                    label_txt = await text
                    translated_labels[field].append(label_txt)

            if cls.Labels is not None:
                await translate_labels(cls.Labels)

            if labels is not None:
                await translate_labels(labels)

            labels = translated_labels
        else:
            labels = None

        return cls(formdata, obj, prefix, data, meta, labels=labels, **kwargs)

    @staticmethod
    async def _get_formdata() -> Optional[Union[MultiDict, CombinedMultiDict, ImmutableMultiDict]]:
        """
        Returns the formdata from a given request. Hnadles multi-dict and json
        content types.
        """
        files = await request.files
        form = await request.form

        if files:
            return CombinedMultiDict((files, form))
        elif form:
            return form
        elif request.is_json:
            return ImmutableMultiDict(await request.get_json())
        else:
            return None

    async def _validate_async(self, validator, field) -> bool:
        """
        Execute async validator.
        """
        try:
            await validator(self, field)
        except ValidationError as error:
            field.errors.append(error.args[0])
            return False
        return True

    async def validate(self, extra_validators=None) -> bool:
        """
        Overload :meth:`validate` to handle custom async validators.
        """
        if extra_validators is not None:
            extra = extra_validators.copy()
        else:
            extra = {}

        async_validators = {}

        # use extra validators to check for StopValidation errors
        completed = []

        def record_status(form, field):
            completed.append(field.name)

        for name, field in self._fields.items():
            func = getattr(self.__class__, f"async_validate_{name}", None)
            if func:
                async_validators[name] = (func, field)
                extra.setdefault[name, []].append(record_status)

        # execute non-async validators
        success = super().validate(extra_validators=extra)

        # execute async validators
        tasks = [self._validate_async(*async_validators[name]) for name in \
            completed]
        async_results = await asyncio.gather(*tasks)

        # check results
        if False in async_results:
            success = False

        return success

    @staticmethod
    def is_submitted() -> bool:
        """
        Consider the form submitted if there is an active request and
        the method is ``POST``, ``PUT``, ``PATCH``, or ``DELETE``.
        """
        return bool(request) and request.method in SUBMIT_METHODS

    async def validate_on_submit(self, extra_validators=None):
        """
        Call :meth:`validate` only if the form is submitted.
        This is a shortcut for ``form.is_submitted() and form.validate()``.
        """
        return self.is_submitted() and \
            await self.validate(extra_validators=extra_validators)

    def hidden_tag(self, *fields):
        """
        Render the form's hidden fields in one call.
        A field is considered hidden if it uses the
        :class:`~wtforms.widgets.HiddenInput` widget.
        If ``fields`` are given, only render the given fields that
        are hidden.  If a string is passed, render the field with that
        name if it exists.
        """
        def hidden_fields(fields):
            for field in fields:
                if isinstance(field, str):
                    field = getattr(self, field, None)

                if field is None or not isinstance(field.widget, HiddenInput):
                    continue

                yield field

        return Markup("\n".join(str(field) for field in hidden_fields(fields or self)))
